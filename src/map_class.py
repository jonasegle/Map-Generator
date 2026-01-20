from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
import matplotlib.patheffects as path_effects
from matplotlib.transforms import Bbox
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
import matplotlib.image as mpimg

from shapely.geometry import Point, Polygon

from typing import Optional, Tuple, List

class Map(object):
    def __init__(self,
                scale: float = 100000.0,
                bounds: Optional[Tuple[float, float, float, float]] = None,
                bounding_shape: Optional[List[Tuple[float, float]]] = None,
                dpi: int = 300,
                font: Tuple[str, int] = ("Arial", 7),
                keep_markers: bool = True,
                attempt_label_repositioning: bool = True,
                settlement_label_padding_cm: float = 0,
                peak_label_padding_cm: float = 0,
                x_inverted: bool = False,
                ):
        """
        scale: map units per pixel
        bounds: [min_easting, min_northing, max_easting, max_northing]
        """
        super().__init__()
        self.scale = scale
        self.geographic_bounds = bounds
        self.bounding_shape = bounding_shape

        self.dpi = dpi
        self.font = font
        self.fontname = font[0]
        self.font_size = font[1]

        self.x_inverted = x_inverted

        self.keep_markers = keep_markers
        """ Whether to keep markers for removed labels."""
        self.attempt_relocation_of_labels = attempt_label_repositioning
        """ Whether to attempt relocation of labels to avoid overlaps.
        If false, overlapping labels are simply removed."""

        # compute image size in centimeters
        min_e, min_n, max_e, max_n = self.geographic_bounds
        
        self.width = (max_e - min_e) / self.scale * 100
        """Width of the map in centimeters"""
        self.height = (max_n - min_n) / self.scale * 100
        """Height of the map in centimeters"""

        print(f"Map size: {self.width:.2f} cm x {self.height:.2f} cm at {self.dpi} dpi")

        # create matplotlib figure and axes
        cm = 1/2.54  # cm per inch
        figsize = (self.width * cm, self.height * cm)
        self.fig = Figure(figsize=figsize, dpi=self.dpi)
        self.canvas = FigureCanvas(self.fig)
        # use a full axes covering the figure so coordinates map directly to pixels
        self.ax = self.fig.add_axes([0, 0, 1, 1])
        self.ax.set_xlim(0, self.width)
        self.ax.set_ylim(0, self.height)
        self.ax.axis("off")

        self.canvas.draw()  # ensure renderer exists

        self.mountain_peaks = []
        self.mountain_huts = []
        self.settlements = []
        self.streets = []
        self.railways = []
        self.water = []
        self.waterways = []

        self.settlement_label_padding_cm = settlement_label_padding_cm
        self.peak_label_padding_cm = peak_label_padding_cm

    def projected_coordinates_to_map_coordinates(self, easting, northing, x_inverted=None) -> Tuple[float, float]:
        if x_inverted is None:
            x_inverted = self.x_inverted
        x = (easting - self.geographic_bounds[0]) / self.scale * 100
        y = (northing - self.geographic_bounds[1]) / self.scale * 100
        if x_inverted:
            x = self.width - x
        return x, y
    
    def is_point_in_bounding_shape(self, point: Tuple[float, float]) -> bool:
        if not self.bounding_shape:
            return True
        bounding_shape_in_map_coords = [self.projected_coordinates_to_map_coordinates(c[0], c[1]) for c in self.bounding_shape]
        polygon = Polygon(bounding_shape_in_map_coords)
        pt = Point(point)
        return polygon.contains(pt)
    
    def apply_bounding_shape_mask(self, coords: List[Tuple[float, float]], tolerance_cm: Optional[float] = 0) -> List[Tuple[float, float]]:
        """
        Filter a list of map-data coordinates by the (optionally expanded) bounding shape.

        tolerance_cm: expansion of the bounding shape in centimeters (map data units).
                      If None, will use self.bounding_shape_tolerance_cm if present, otherwise 0.5 cm.
        """
        if not self.bounding_shape:
            return coords

        # resolve tolerance (cm in map data coordinates)
        tol = tolerance_cm if tolerance_cm is not None else getattr(self, "bounding_shape_tolerance_cm", 0.5)
        try:
            tol = float(tol)
        except Exception:
            tol = 0.5

        # build polygon in map data coordinates
        bounding_shape_in_map_coords = [self.projected_coordinates_to_map_coordinates(c[0], c[1]) for c in self.bounding_shape]
        poly = Polygon(bounding_shape_in_map_coords)

        # expand polygon by tolerance (positive = expand, negative = shrink)
        if tol != 0:
            try:
                poly = poly.buffer(tol)
            except Exception:
                # fallback: if buffer fails, use original polygon
                poly = Polygon(bounding_shape_in_map_coords)

        # keep points that lie inside (or on the boundary) of the (expanded) polygon
        filtered = [pt for pt in coords if poly.covers(Point(pt))]

        return filtered
    
    def get_bbox_in_map_coordinates(self, artist, padding_cm: float = 0) -> Tuple[float, float, float, float]:
        """ 
        Get bounding box of an artist as 4-tuple in map data coordinates.
        Returns (x0, y0, x1, y1) in map data coordinates.
        """
        bbox_disp = artist.get_tightbbox(self.canvas.get_renderer())
        bbox_data = bbox_disp.transformed(self.ax.transData.inverted())

        if padding_cm != 0:
            bbox_data = Bbox.from_extents(
                bbox_data.x0 - padding_cm,
                bbox_data.y0 - padding_cm,
                bbox_data.x1 + padding_cm,
                bbox_data.y1 + padding_cm,
            )

        return bbox_data.x0, bbox_data.y0, bbox_data.x1, bbox_data.y1
    
    def draw_image(self, image_path: str, position: Tuple[float, float], width: float = 3.8):
        image = mpimg.imread(image_path)

        zoom_factor = width / (image.shape[1] / 72 * 2.54)
        imagebox = OffsetImage(image, zoom=zoom_factor)

        # draw a white background behind the image using bboxprops; enable frameon
        bboxprops = {"boxstyle": "Round,pad=0.08, rounding_size=0.5", "facecolor": "white", "edgecolor": "none"}
        ab = AnnotationBbox(imagebox,
                            position,
                            xycoords="data",
                            frameon=True,
                            bboxprops=bboxprops,
                            box_alignment=(0.5, 0.5),
                )
        ab.set_zorder(10)
        ab.set_clip_on(False)
        self.ax.add_artist(ab)

        ab.meta = {"name": "logo"}
        ab.bbox = self.get_bbox_in_map_coordinates(ab)
        ab.tags = set(["logo"])

    def draw_water(self, color: str= "0.75", draw_inners: bool = True):
        for water in self.water:
            verts = [self.projected_coordinates_to_map_coordinates(c[0], c[1]) for c in water["coords"]]
            verts = self.apply_bounding_shape_mask(verts, tolerance_cm=0.5)
            if not verts:
                continue
            xs, ys = zip(*verts)
            artist = self.ax.fill(xs, ys, facecolor=color, edgecolor=color, linewidth=0.1)
            artist[0].set_zorder(0)  # set zorder to background
            if draw_inners and "inners" in water:
                for inner in water["inners"]:
                    inner_verts = [self.projected_coordinates_to_map_coordinates(c[0], c[1]) for c in inner]
                    #inner_verts = self.apply_bounding_shape_mask(inner_verts, tolerance_cm=0.5)s
                    if not inner_verts:
                        continue
                    xs_inner, ys_inner = zip(*inner_verts)
                    inner_artist = self.ax.fill(xs_inner, ys_inner, facecolor="white", edgecolor="white", linewidth=0.1)
                    inner_artist[0].set_zorder(1)  # set zorder above water area

    def draw_waterways(self, color: str= "0.75"):
        for waterway in self.waterways:
            verts = [self.projected_coordinates_to_map_coordinates(c[0], c[1]) for c in waterway["coords"]]
            verts = self.apply_bounding_shape_mask(verts, tolerance_cm=0.5)
            if not verts:
                continue

            waterway_type = (waterway.get("waterway") or "").lower()
            if waterway_type == "river":
                lw = 1.0
                clr = color
            elif waterway_type == "stream":
                lw = 0.25
                clr = "black"
            else:
                lw = 0.25
                clr = color

            linestyle = "-"
            if waterway.get("tunnel") in ("yes", "true", "1", "underground", "flooded"):
                linestyle = "--"

            xs, ys = zip(*verts)
            artist = self.ax.plot(xs, ys, color=clr, linewidth=lw, linestyle=linestyle)
            artist[0].set_zorder(0)  # set zorder to background
                
    def draw_streets(self):
        # Draw streets with width based on their OSM 'highway' type.
        # Larger/more important roads get a larger linewidth.
        # Linewidth values are in points (Matplotlib default).
        major_style = {'color': '0.25', 'linewidth': 1.5, 'alpha': 1.0, 'solid_capstyle': 'round'}
        trunk_style = {'color': '0.25', 'linewidth': 1.4, 'alpha': 1.0, 'solid_capstyle': 'round'}
        primary_style = {'color': '0.25', 'linewidth': 1.2, 'alpha': 1.0, 'solid_capstyle': 'round'}
        secondary_style = {'color': '0.25', 'linewidth': 0.8, 'alpha': 1.0, 'solid_capstyle': 'round'}
        tertiary_style = {'color': '0.25', 'linewidth': 0.5, 'alpha': 1.0, 'solid_capstyle': 'round'}
        residential_style = {'color': '0.25', 'linewidth': 0.35, 'alpha': 1.0, 'solid_capstyle': 'round'}
        service_style = {'color': '0', 'linewidth': 0.25, 'alpha': 1.0, 'solid_capstyle': 'round'}
        path_style = {'color': '0', 'linewidth': 0.5, 'alpha': 1.0, 'solid_capstyle': 'round'}
        default_style = {'color': '0', 'linewidth': 0.25, 'alpha': 1.0, 'solid_capstyle': 'round'}

        for street in self.streets:
            verts = [self.projected_coordinates_to_map_coordinates(c[0], c[1]) for c in street["coords"]]
            verts = self.apply_bounding_shape_mask(verts, tolerance_cm=0.5)
            if not verts:
                continue
            xs, ys = zip(*verts)

            hwy = (street.get("highway") or "").lower()

            # coarse categorization to catch values like 'motorway_link' etc.
            if "motorway" in hwy:
                color = major_style['color']
                lw = major_style['linewidth']
                a = major_style['alpha']
            elif "trunk" in hwy:
                color = trunk_style['color']
                lw = trunk_style['linewidth']
                a = trunk_style['alpha']
            elif "primary" in hwy:
                color = primary_style['color']
                lw = primary_style['linewidth']
                a = primary_style['alpha']
            elif "secondary" in hwy:
                color = secondary_style['color']
                lw = secondary_style['linewidth']
                a = secondary_style['alpha']
            elif "tertiary" in hwy:
                color = tertiary_style['color']
                lw = tertiary_style['linewidth']
                a = tertiary_style['alpha']
            elif hwy in ("residential", "unclassified", "living_street"):
                color = residential_style['color']
                lw = residential_style['linewidth']
                a = residential_style['alpha']
            elif hwy in ("service",):
                color = service_style['color']
                lw = service_style['linewidth']
                a = service_style['alpha']
            elif hwy in ("path", "footway", "track", "cycleway"):
                color = path_style['color']
                lw = path_style['linewidth']
                a = path_style['alpha']
            else:
                color = default_style['color']
                lw = default_style['linewidth']
                a = default_style['alpha']

            linestyle = "-"
            if street.get("tunnel") in ("yes", "true", "1"):
                a *= 0.5
                linestyle = "--"
                
            if street.get("sac_scale") in ("mountain_hiking", "demanding_mountain_hiking", "difficult_mountain_hiking"):
                linestyle = "--"

            if street.get("sac_scale") in ("alpine_hiking", "demanding_alpine_hiking", "difficult_alpine_hiking"):
                linestyle = ":"

            self.ax.plot(xs, ys, color=color, linewidth=lw, alpha=a, linestyle=linestyle, solid_capstyle='round')

    def draw_railways(self):
        for railway in self.railways:
            verts = [self.projected_coordinates_to_map_coordinates(c[0], c[1]) for c in railway["coords"]]
            verts = self.apply_bounding_shape_mask(verts, tolerance_cm=0.5)
            if not verts:
                continue
            xs, ys = zip(*verts)

            alpha = 1.0
            if railway.get("tunnel") in ("yes", "true", "1"):
                alpha = 0.5

            self.ax.plot(xs, ys, color="0.375", linewidth=1, alpha=alpha, solid_capstyle='round')
            self.ax.plot(xs, ys, color="1", linewidth=0.5, linestyle=(0, (5,5)), alpha=alpha)

    def draw_settlements(self, color: str = "black", fontweight: str = "bold", italic: bool = False):
        # store artists per settlement name
        for settlement in self.settlements:
            x, y = self.projected_coordinates_to_map_coordinates(settlement["easting"], settlement["northing"])

            if settlement.get("name") in set(["Breuil-Cervinia"]):
                continue

            # determine place/type and choose fontsize multiplier
            place = (settlement.get('place') or '')
            place = place.lower() if isinstance(place, str) else ''

            """ if 'neighbourhood' in place or 'locality' in place:
                continue """

            #print(f"Settlement {settlement['name']} place/type: '{place}'")

            # coarse size mapping (larger place -> larger label)
            if 'city' in place:
                factor = 1.6
            elif 'town' in place:
                factor = 1.3
            elif 'village' in place:
                factor = 1.0
            elif 'suburb' in place:
                factor = 0.9
            elif 'hamlet' in place or 'neighbourhood' in place or 'locality' in place:
                factor = 0.8
            else:
                # default / unknown settlement
                factor = 0.9

            # small population-based boost if available
            pop = settlement.get('population')
            if pop is not None:
                try:
                    p = int(pop)
                    if p >= 100000:
                        factor = max(factor, 1.8)
                    elif p >= 50000:
                        factor = max(factor, 1.5)
                    elif p >= 10000:
                        factor = max(factor, 1.2)
                except Exception:
                    # ignore non-numeric population
                    pass
            
            #print(f"Drawing settlement label for {settlement['name']} at map coords ({x:.2f}, {y:.2f}) with factor {factor:.2f}")

            fontsize = self.font_size * factor

            label = self.ax.text(x, y, settlement["name"],
                                ha="center",
                                va="center",
                                fontfamily=self.fontname,
                                fontsize=fontsize,
                                fontstyle="italic" if italic else "normal",
                                fontweight=fontweight,
                                color=color,
                )

            label.set_path_effects([path_effects.Stroke(linewidth=2, foreground='white'),
                    path_effects.Normal()])

            label.tags = set([f"{settlement['name']}", "settlement", "label"])
            label.meta = settlement
            label.bbox = self.get_bbox_in_map_coordinates(label, padding_cm=self.settlement_label_padding_cm)

    def draw_mountain_peaks(self, color: str = "black", fontweight: str = "bold", italic: bool = False):
        #y_line_offset_cm = self.y_line_offset_in_data_coords(self.font)
        # store artists per peak name
        for peak in self.mountain_peaks:
            x, y = self.projected_coordinates_to_map_coordinates(peak["easting"], peak["northing"])
            #print(f"Drawing peak label for {peak['name']} at map coords ({x:.2f}, {y:.2f})")

            if peak.get("name") in set(["Zinalrothorn", "Punta Marinelli", "Platthorn", "Aiguille du Châtelet", "Grand Gendarme", "Bösentrift", "Büchsentaljoch"]):
                continue

            marker = self.ax.text(x, y, "▲",
                                ha="center",
                                va="center",
                                fontsize=self.font_size,
                                color=color,
                )
            label_text = ""
            if peak.get("name") is not None:
                label_text += f"{peak['name']}"
            if peak.get("elevation") is not None:
                if label_text:
                    label_text += f"\n{int(peak['elevation'])}m"
                else:
                    label_text += f"{int(peak['elevation'])}m"
            label = self.ax.annotate(text = label_text,
                                    xy = (x, y),
                                    xytext = (0, -0.75),  # offset below the peak marker
                                    textcoords = 'offset fontsize',
                                    ha="center",
                                    va="top",
                                    fontsize=self.font_size,
                                    color=color,
                                    fontweight=fontweight,
                )

            label.set_path_effects([path_effects.Stroke(linewidth=2, foreground='white'),
                    path_effects.Normal()])
            
            marker.tags = set([f"{peak['name']}", "mountain_peak", "marker"])
            marker.meta = peak
            marker.bbox = self.get_bbox_in_map_coordinates(marker)
            marker.label = label  # link to label

            label.tags = set([f"{peak['name']}", "mountain_peak", "label"])
            label.meta = peak
            label.bbox = self.get_bbox_in_map_coordinates(label, padding_cm=self.peak_label_padding_cm)
            label.marker = marker  # link to marker

    def draw_mountain_huts(self, color: str = "black", fontweight: str = "normal", italic: bool = False):
        for hut in self.mountain_huts:
            x, y = self.projected_coordinates_to_map_coordinates(hut["easting"], hut["northing"])

            marker = self.ax.text(x, y, "⌂",
                                ha="center",
                                va="center",
                                fontsize=self.font_size,
                                fontweight="bold",
                                color=color,
                                bbox=dict(boxstyle="Round,pad=0.05, rounding_size=0.25", fc="white", ec="none"),
                )
            label = self.ax.annotate(text = f"{hut['name']}",
                                    xy = (x, y),
                                    xytext = (0, -0.75),  # offset below the hut marker
                                    textcoords = 'offset fontsize',
                                    ha="center",
                                    va="top",
                                    fontsize=self.font_size * 0.8,
                                    fontweight=fontweight,
                                    fontstyle="italic" if italic else "normal",
                                    color="Black",
                )

            
            label.set_path_effects([path_effects.Stroke(linewidth=2, foreground='white'),
                    path_effects.Normal()])
            
            marker.tags = set([f"{hut['name']}", "mountain_hut", "marker"])
            marker.meta = hut
            marker.bbox = self.get_bbox_in_map_coordinates(marker)
            marker.label = label  # link to label

            label.tags = set([f"{hut['name']}", "mountain_hut", "label"])
            label.meta = hut
            label.bbox = self.get_bbox_in_map_coordinates(label)

    def draw_bounding_shape(self):
        if not self.bounding_shape:
            return
        verts = [self.projected_coordinates_to_map_coordinates(c[0], c[1]) for c in self.bounding_shape]
        xs, ys = zip(*verts)
        self.ax.plot(xs, ys, color="red", linewidth=1.0, linestyle="--")

    def y_line_offset_in_data_coords(self, font):
        # create a dummy text artist to measure
        txt = self.ax.text(0, 0, "Mg", fontsize=font[1], fontname=font[0])
        bbox_disp = txt.get_window_extent(self.canvas.get_renderer())
        txt.remove()
        height_data = bbox_disp.height / self.dpi * 2.54  # convert pixels to cm
        return height_data * 1.2  # line spacing factor
    
    def is_bbox_out_of_map_bounds(self, bbox):
        if bbox is None:
            return False
        x1, y1, x2, y2 = bbox
        img_w = self.width
        img_h = self.height
        if x1 < 0 or x2 > img_w:
            return True
        if y1 < 0 or y2 > img_h:
            return True
        return False
    
    def is_bbox_out_of_bounding_shape(self, bbox):
        if not self.bounding_shape or bbox is None:
            return False
        x1, y1, x2, y2 = bbox
        for corner in [(x1, y1), (x1, y2), (x2, y1), (x2, y2)]:
            if not self.is_point_in_bounding_shape(corner):
                return True
        return False
    
    def are_bboxes_overlapping(self, b1, b2):
        if b1 is None or b2 is None:
            return False
        x1_1, y1_1, x2_1, y2_1 = b1
        x1_2, y1_2, x2_2, y2_2 = b2
        if x1_1 > x2_2 or x1_2 > x2_1:
            return False
        if y1_1 > y2_2 or y1_2 > y2_1:
            return False
        return True

    def find_overlapping_elements(self, *targets, candidates = None):
        if not targets:
            return []

        if candidates is None:
            candidates = self.ax.findobj(lambda artist: getattr(artist, "bbox", None) is not None)
        overlapping = []
        for target in targets:
            if not hasattr(target, "bbox"):
                continue
            target_bbox = target.bbox
            for candidate in candidates:
                if candidate in set(targets) or not hasattr(candidate, "bbox"):
                    continue
                candidate_bbox = candidate.bbox
                if self.are_bboxes_overlapping(target_bbox, candidate_bbox):
                    overlapping.append(candidate)
        return overlapping

    def compute_group_priority(self, meta):
        """
        Compute a comparable priority tuple for a group's meta.
        Higher tuples are preferred when resolving collisions.

        Priority tuple structure:
         (kind_priority, primary_value, secondary_value)
        where kind_priority: peaks > settlements > others
        For peaks: primary=prominence (or 0), secondary=elevation (or 0)
        For settlements: primary=place_rank, secondary=population or fontsize
        """
        # detect logo
        if meta == {"name": "logo"}:
            return (10, 0, 0)

        # detect peak (has elevation/prominence)
        if isinstance(meta, dict) and meta["type"] == "mountain_peak":
            kind = 4
            prom = meta.get('prominence') or 0
            try:
                prom = float(prom)
            except Exception:
                prom = 0
            ele = meta.get('elevation') or 0
            try:
                ele = float(ele)
            except Exception:
                ele = 0
            return (kind, prom, ele)
        
        if isinstance(meta, dict) and meta["type"] == "mountain_hut":
            kind = 3
            if meta.get("name") == "Zsigmondy Hütte":
                kind = 10
            return (kind, 0, 0)

        # settlements and others
        if isinstance(meta, dict) and meta["type"] == "settlement":
            kind = 6 if ('place' in meta or 'population' in meta or '_fontsize' in meta) else 1

            place = (meta.get('place') or meta.get('type') or '')
            place = place.lower() if isinstance(place, str) else ''
            # rank places roughly
            if 'city' in place:
                place_rank = 5
            elif 'town' in place:
                place_rank = 4
            elif 'suburb' in place:
                place_rank = 3
            elif 'village' in place:
                place_rank = 2
            elif 'hamlet' in place or 'neighbourhood' in place or 'locality' in place:
                place_rank = 1
            else:
                place_rank = 1

            pop = meta.get('population')
            pop_val = 0
            if pop is not None:
                try:
                    pop_val = int(pop)
                except Exception:
                    pop_val = 0

            # fallback to fontsize if population missing
            fontsize = meta.get('_fontsize') or 0

            return (kind, place_rank, pop_val or int(fontsize))

        return (0, 0, 0)
    
    def find_first_artist_with_tag(self, tag, candidates=None):
        if candidates is None:
            candidates = self.ax.findobj(lambda artist: getattr(artist, "tags", None) is not None)
        for artist in candidates:
            try:
                if tag in artist.tags:
                    return artist
            except Exception:
                continue
        return None
    
    def find_artists_with_tag(self, tag, candidates=None):
        if candidates is None:
            candidates = self.ax.findobj(lambda artist: getattr(artist, "tags", None) is not None)
        return [artist for artist in candidates if tag in artist.tags]

    def resolve_overlaps(self):
        """
        Resolve overlapping labels in self._artists.
        Priority rules:
         - mountain peaks (by prominence then elevation) win over settlements
         - settlements prioritized by place type and population/fontsize
         - out-of-map labels are removed
        """
        self.canvas.draw()  # ensure renderer exists for bbox calculations
        
        has_meta_and_visible = lambda artist: getattr(artist, "meta", None) is not None and artist.get_visible()
        visible_artists_with_meta = [a for a in self.ax.findobj(has_meta_and_visible)]

        artists_ordered = sorted(visible_artists_with_meta,
                                key=lambda a: self.compute_group_priority(a.meta),
                                reverse=True)
   
        removed = set()
        placed = set()

        def remove_artist(artist):
            if "marker" in artist.tags and hasattr(artist, "label") and self.keep_markers:
                remove_artist(artist.label)
            artist.set_visible(False)
            removed.add(artist)

        def keep_artist(artist):
            placed.add(artist)

        def is_overlapping_with_placed(artist):
            candidates = set(visible_artists_with_meta).difference(removed)
            overlapping_artists = self.find_overlapping_elements(artist, candidates=candidates)

            if hasattr(artist, "marker") and artist.marker in overlapping_artists:
                overlapping_artists.remove(artist.marker)

            return bool(set(overlapping_artists).intersection(placed))

        def attempt_relocation_of_label(artist):
            relocated = False
            new_positions = [
                (0, 0.75),  # up
            ]
            for new_pos in new_positions:
                if new_pos[1] > 0:
                    artist.set_va("bottom")
                artist.set_position(new_pos)
                # update bbox
                artist.bbox = self.get_bbox_in_map_coordinates(artist, padding_cm=self.peak_label_padding_cm)
                # check if out of bounding shape
                if self.is_bbox_out_of_bounding_shape(artist.bbox):
                    #print(f"Relocated label {artist} to ({new_pos[0]:.2f}, {new_pos[1]:.2f}) is out of bounding shape, reverting.")
                    continue

                # check for overlaps again
                if not is_overlapping_with_placed(artist):
                    keep_artist(artist)
                    relocated = True
                    #print(f"Relocated label {artist.meta['name']} to ({new_pos[0]:.2f}, {new_pos[1]:.2f}) to avoid overlap.")
                    break
            return relocated

        # first remove out-of-bounds groups
        logo = None
        for artist in artists_ordered:
            if artist in removed:
                continue

            if artist.meta.get("name") == "logo":
                logo = artist
                keep_artist(artist)
                continue

            bbox = artist.bbox
            if "marker" in artist.tags:
                bbox = self.get_bbox_in_map_coordinates(artist, padding_cm=-0.2)
                
            if self.is_bbox_out_of_bounding_shape(bbox):
                remove_artist(artist)
                continue

            # If overlap with already placed high-priority labels, remove or relocate
            if is_overlapping_with_placed(artist):
                if self.attempt_relocation_of_labels and "mountain_peak" in artist.tags:
                    # try to relocate label
                    relocated = False
                    if "label" in artist.tags:
                        relocated = attempt_relocation_of_label(artist)
                    if not relocated:
                        # could not relocate, remove
                        remove_artist(artist)
                else:
                    remove_artist(artist)
            else:
                """ if artist.meta['name'] in set(["Aiguille du Châtelet","Aiguille de l'Aigle","Büchsentaljoch", "Mont Berrio Blanc", "Hochwanner", "Rauher Kopf", "Gacher Blick", "Judenkopf", "Issentalköpfl"]):
                if "marker" in artist.tags:
                    label = artist.label
                    label.remove()
                    removed.add(label) """
                keep_artist(artist)
                        

        markers = self.find_artists_with_tag("marker")
        for m in markers:
            if hasattr(m, "label") and m.label in removed and m not in removed:
                font_size = m.get_fontsize()
                m.set_fontsize(font_size * 0.75)
                #print(f"Reducing marker size for {m.meta['name']} from {font_size:.1f} to {m.get_fontsize():.1f} due to label removal.")

        #print(f"removed: {[a.meta['name'] for a in removed]}")
        #print(f"placed: {[a.meta['name'] for a in placed]}")

        # debug
        # print summary
        print(f"Removed {len(removed)} overlapping or out-of-bounds artists.")


        num_mountain_peak_labels = 0
        num_mountain_peak_markers = 0
        num_settlement_labels = 0
        for p in placed:
            if "mountain_peak" in p.tags and "label" in p.tags:
                num_mountain_peak_labels += 1
            if "mountain_peak" in p.tags and "marker" in p.tags:
                num_mountain_peak_markers += 1
            if "settlement" in p.tags and "label" in p.tags:
                num_settlement_labels += 1
        print(f"{len(placed)} artists placed.")
        print(f"  of which {num_mountain_peak_labels} mountain peak labels and {num_mountain_peak_markers} mountain peak markers.")
        print(f"  of which {num_settlement_labels} settlement labels.")


    def save(self, filename):
        # finalize and save as grayscale PNG
        # ensure white background
        self.fig.patch.set_facecolor("white")
        # draw once more to ensure final rendering
        self.canvas.draw()
        # save
        self.fig.savefig(filename, dpi=self.dpi, format="png", facecolor=self.fig.get_facecolor(), bbox_inches="tight", pad_inches=0)
    
    def save_as_pdf(self, filename):
        # finalize and save as grayscale PDF
        # ensure white background
        self.fig.patch.set_facecolor("white")
        # draw once more to ensure final rendering
        self.canvas.draw()
        # save
        self.fig.savefig(filename, dpi=self.dpi, format="pdf", facecolor=self.fig.get_facecolor(), bbox_inches="tight", pad_inches=0)

if __name__ == "__main__":
    from functools import reduce
    from pyproj import Transformer
    import shapefile

    from openstreetmap_api import OpenStreetMapAPI
    import json

    shape = shapefile.Reader("inputs/28B.shp")
    #first feature of the shapefile
    feature = shape.shapeRecords()[0]
    first = feature.shape.__geo_interface__
    #print(first) # (GeoJSON format)

    shape_vertices_in_projected_coordinates = []
    for coordinate in first.get("coordinates", [])[0]:
        shape_vertices_in_projected_coordinates.append((coordinate[0], coordinate[1]))

    eastings = list(map(lambda x : float(x[0]), shape_vertices_in_projected_coordinates))
    northings = list(map(lambda x : float(x[1]), shape_vertices_in_projected_coordinates))

    min_easting = reduce(lambda x, y : min(x, y), eastings)
    min_northing = reduce(lambda x, y :  min(x, y), northings)
    max_easting = reduce(lambda x, y :  max(x, y), eastings)
    max_northing = reduce(lambda x, y :  max(x, y), northings)

    #print(min_easting, min_northing, max_easting, max_northing)

    shape_vertices_in_geographical_coordinates = []

    transformer_proj_to_geo = Transformer.from_crs("EPSG:25832", "EPSG:4326", always_xy=False)

    for coordinate in first.get("coordinates", [])[0]:
        shape_vertices_in_geographical_coordinates.append(transformer_proj_to_geo.transform(coordinate[0], coordinate[1]))
    
    #print(shape_vertices_in_geographical_coordinates)

    latitudes = list(map(lambda x : float(x[0]), shape_vertices_in_geographical_coordinates))
    longitudes = list(map(lambda x : float(x[1]), shape_vertices_in_geographical_coordinates))

    # Example coordinates for Switzerland
    min_lat = reduce(lambda x, y : min(x, y), latitudes)
    min_lon = reduce(lambda x, y : min(x, y), longitudes)
    max_lat = reduce(lambda x, y : max(x, y), latitudes)
    max_lon = reduce(lambda x, y : max(x, y), longitudes)

    osm_api = OpenStreetMapAPI()

    with open('map_data.json', 'r') as f:
        data = json.load(f)
        mountain_peaks = data['mountain_peaks']
        lakes = data['lakes']
        waterways = data['waterways']
        streets = data['streets']
        settlements = data['settlements']
    
    map_bounds = (min_easting, min_northing, max_easting, max_northing)

    bounding_shape = shape_vertices_in_projected_coordinates

    image_map = Map(
        scale=100000.0,
        bounds=map_bounds,
        bounding_shape=bounding_shape,
        dpi=300,
        font=("Arial", 7),
        fontweight="bold",
        keep_markers=True,
        attempt_label_repositioning=True,
    )

    image_map.mountain_peaks = mountain_peaks
    image_map.settlements = settlements
    image_map.streets = streets
    image_map.lakes = lakes
    image_map.waterways = waterways

    image_map.draw_image("logo_final_nebeneinander.png", position=(image_map.width / 2, 0.5), zoom=0.1)

    image_map.draw_mountain_peaks()
    image_map.draw_water()
    image_map.draw_waterways()
    image_map.draw_settlements()
    image_map.draw_streets()

    image_map.resolve_overlaps()

    image_map.draw_bounding_shape()

    image_map.save("map.png")
