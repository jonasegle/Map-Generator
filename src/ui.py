import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import yaml
import subprocess
import os
import sys
import tempfile
from generate_shapefile import generate_shapefile

def show_error(title, message):
    """Show error in both GUI and terminal"""
    print(f"\n{'='*80}")
    print(f"ERROR: {title}")
    print(f"{message}")
    print(f"{'='*80}\n")
    messagebox.showerror(title, message)

def show_info(title, message):
    """Show info in both GUI and terminal"""
    print(f"\n{'='*80}")
    print(f"{title}")
    print(f"{message}")
    print(f"{'='*80}\n")
    messagebox.showinfo(title, message)

class ToolTip:
    """Create a tooltip for a given widget"""
    def __init__(self, widget, text='Widget info'):
        self.widget = widget
        self.text = text
        self.widget.bind("<Enter>", self.enter)
        self.widget.bind("<Leave>", self.leave)
        self.tooltip_window = None

    def enter(self, event=None):
        x, y, cx, cy = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 20
        y += self.widget.winfo_rooty() + 20
        
        # Create tooltip window
        self.tooltip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        
        label = tk.Label(tw, text=self.text, justify='left',
                        background='#ffffe0', relief='solid', borderwidth=1,
                        font=('Arial', 9, 'normal'), wraplength=300)
        label.pack(ipadx=1)

    def leave(self, event=None):
        if self.tooltip_window:
            self.tooltip_window.destroy()
            self.tooltip_window = None
    
# Parameter descriptions for tooltips
PARAMETER_DESCRIPTIONS = {
    "input_file": "Input geometry file (.shp or .geojson) containing the geometry to process. Leave empty to generate from AOI parameters.",
    "input_folder": "Folder containing multiple geometry files for bulk processing (only when use_bulk is enabled)",
    "use_bulk": "Enable to process multiple files from input_folder instead of a single input_file",
    "rasterfile": "Digital Terrain Model (.tif) file providing elevation data. Leave empty to download from OpenTopography.",
    "auto_download_dem": "Automatically download DEM from OpenTopography if rasterfile is not specified",
    "dem_type": "DEM source: COP30 (Copernicus 30m), NASADEM (NASA 30m), or SRTMGL1 (SRTM 30m)",
    "opentopo_api_key": "Your OpenTopography API key (get from https://portal.opentopography.org)",
    "prefer_etrs89_in_europe": "Use ETRS89 (EPSG:258xx) for European coordinates instead of WGS84 UTM",
    "output_folder": "Output folder where generated files (STL/G-code) will be saved",
    "gpxfile": "GPS track file (.gpx) for laser engraving paths",
    "scale": "Map scale factor (e.g., 50000 = 1:50,000). Higher values = smaller physical output",
    "add_base_height": "Base thickness added to the bottom of the model (in mm)",
    "variable_base_height": "When true, adjusts base height dynamically based on terrain variation",
    "height_scale": "Height scaling factor when variable_base_height is enabled (higher = more compressed)",
    "z_scale": "Vertical exaggeration factor for terrain height (1.0 = real scale, 2.0 = double height, 0.5 = half height)",
    "offset_mm": "Buffer distance around geometry boundaries (in mm)",
    "window_size": "Size of the filter window for outlier detection (larger = more smoothing)",
    "threshold": "Threshold value for outlier detection (higher = less sensitive)",
    "lower_water_surface": "Enable automatic water surface detection and adjustment",
    "water_offset_mm": "Amount to lower detected water surfaces (in mm)",
    "water_min_region_size": "Minimum number of pixels for a flat region to be considered water (higher = fewer small areas detected)",
    "water_variance_threshold": "Maximum local variance for a region to be considered flat/water (lower = stricter detection)",
    "water_closing_iterations": "Number of morphological closing iterations to fill holes in water mask (higher = more smoothing)",
    "generate_ngc": "Generate G-code files (.ngc) for CNC machining",
    "generate_laser_gcode": "Generate laser engraving G-code following GPS tracks",
    "rotate_90": "Rotate the model 90 degrees for machining orientation",
    "ngc_grid_resolution": "Grid resolution for G-code generation [X, Y] (in mm)",
    "bit_radius": "Radius of the cutting bit for G-code toolpath compensation (in mm)",
    "start_from_back": "Start machining from the back of the workpiece",
    "generate_stl": "Generate 3D printable STL files",
    "stl_grid_resolution": "Grid resolution for STL generation [X, Y] (in mm)",
    "alternate_spacing": "Use alternating Y-spacing for toolpath optimization",
    "spacing_y": "Y-axis spacing values [spacing1, spacing2] when alternate_spacing is enabled",
    "generate_aoi": "Generate AOI shapefile from parameters below (only if input_file is empty)",
    "aoi_name": "Name for the generated AOI (used in output folder and shapefile naming)",
    "aoi_shape_type": "Shape type for generated AOI: circle, square, rectangle, or hexagon",
    "aoi_center_coords": "Center coordinates as 'latitude, longitude' (can paste directly from Google Maps)",
    "aoi_crs_epsg": "Output CRS EPSG code for generated AOI shapefile (leave empty to automatically select optimal UTM zone)",
    "aoi_dimension1_mm": "Dimension in mm - Circle: radius | Square: side length | Rectangle: width (X) | Hexagon: inner radius",
    "aoi_dimension2_mm": "Rectangle height (Y) in mm - only used when shape is rectangle, ignored for other shapes",
    "save_generated_shapefile": "Save the generated AOI shapefile to disk (otherwise it's created temporarily)",
    "save_geojson": "Also save the generated AOI as GeoJSON in WGS84 format"
}


class ConfigEditor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Map Generation Configuration Editor")
        self.geometry("950x700")
        self.minsize(930, 500)

        self.config_file = tk.StringVar()
        self.config_data = {}
        self.config_folder = os.path.abspath('src/config')
        self.widgets = {}  # Track widgets for updating values
        self.dimension_labels = {}  # Track dimension labels for dynamic updates
        self.dimension_widgets = {}  # Track dimension entry widgets for dynamic updates

        # Configure styles
        self.configure(bg='#f0f0f0')
        
        self.create_widgets()

    def create_widgets(self):
        # Header frame
        header_frame = tk.Frame(self, bg='#f0f0f0')
        header_frame.pack(fill="x", padx=10, pady=5)
        
        # Dropdown for config files
        tk.Label(header_frame, text="Select Config File:", font=("Arial", 10, "bold"), bg='#f0f0f0').pack(anchor='w')
        dropdown_frame = tk.Frame(header_frame, bg='#f0f0f0')
        dropdown_frame.pack(fill="x", pady=5)
        
        self.config_dropdown = ttk.Combobox(dropdown_frame, textvariable=self.config_file, width=40)
        self.config_dropdown.pack(side="left")
        self.config_dropdown.bind("<<ComboboxSelected>>", self.load_config)
        
        # Refresh button for config files
        refresh_btn = tk.Button(dropdown_frame, text="Refresh", command=self.load_config_files)
        refresh_btn.pack(side="left", padx=(10, 0))
        
        self.load_config_files()

        # Separator
        ttk.Separator(self, orient='horizontal').pack(fill='x', pady=5)

        # Frame for config parameters with scrollbar
        self.params_frame = tk.Frame(self, bg='#f0f0f0')
        self.canvas = tk.Canvas(self.params_frame, bg='white')
        self.scrollbar = ttk.Scrollbar(self.params_frame, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = tk.Frame(self.canvas, bg='white')

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(
                scrollregion=self.canvas.bbox("all")
            )
        )

        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        # Mouse wheel scrolling
        def _on_mousewheel(event):
            self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        self.canvas.bind("<MouseWheel>", _on_mousewheel)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.params_frame.pack(pady=10, fill=tk.BOTH, expand=True)

        # Bottom button frame
        button_frame = tk.Frame(self, bg='#f0f0f0')
        button_frame.pack(fill="x", padx=10, pady=5)
        
        # Button to generate map
        generate_btn = tk.Button(button_frame, text="Generate Map", command=self.generate_data, 
                               bg='#4CAF50', font=("Arial", 10, "bold"), pady=5)
        generate_btn.pack(side="left", padx=(0, 5))
        
        # Button to save config
        save_btn = tk.Button(button_frame, text="Save Config", command=self.save_config,
                           bg='#2196F3', font=("Arial", 10, "bold"), pady=5)
        save_btn.pack(side="left", padx=5)
        
        # Button to save config as
        save_as_btn = tk.Button(button_frame, text="Save Config As...", command=self.open_save_dialog,
                              bg='#FF9800', font=("Arial", 10, "bold"), pady=5)
        save_as_btn.pack(side="left", padx=5)

    def get_dimension1_label(self, shape_type):
        """Get the appropriate label for dimension1 based on shape type"""
        labels = {
            'circle': 'aoi_dimension1_mm (radius):',
            'square': 'aoi_dimension1_mm (side):',
            'rectangle': 'aoi_dimension1_mm (width):',
            'hexagon': 'aoi_dimension1_mm (inner radius):'
        }
        return labels.get(shape_type, 'aoi_dimension1_mm:')
    
    def get_dimension2_label(self, shape_type):
        """Get the appropriate label for dimension2 based on shape type"""
        labels = {
            'rectangle': 'aoi_dimension2_mm (height):',
        }
        return labels.get(shape_type, 'aoi_dimension2_mm:')
    
    def update_dimension_labels(self, shape_type):
        """Update dimension labels when shape type changes"""
        if 'dimension1' in self.dimension_labels:
            self.dimension_labels['dimension1'].config(text=self.get_dimension1_label(shape_type))
        if 'dimension2' in self.dimension_labels:
            self.dimension_labels['dimension2'].config(text=self.get_dimension2_label(shape_type))
        
        # Update dimension2 widget state based on shape type
        if 'dimension2' in self.dimension_widgets:
            widget_info = self.dimension_widgets['dimension2']
            entry = widget_info.get('entry')
            helper_label = widget_info.get('helper_label')
            
            if shape_type == 'rectangle':
                # Enable for rectangle
                if entry and entry.winfo_exists():
                    entry.config(state='normal')
                if helper_label and helper_label.winfo_exists():
                    helper_label.pack_forget()
            else:
                # Disable for other shapes
                if entry and entry.winfo_exists():
                    entry.config(state='disabled')
                if helper_label and helper_label.winfo_exists():
                    helper_label.pack(side="left", padx=(5, 0))

    def load_config_files(self):
        config_files = [f for f in os.listdir(self.config_folder) if f.endswith('.yaml')]
        self.config_dropdown['values'] = config_files

    def load_config(self, event=None):
        config_filename = self.config_file.get()
        if not config_filename:
            show_error("Error", "No config file selected.")
            return
        config_path = os.path.join(self.config_folder, config_filename)
        with open(config_path, 'r') as file:
            self.config_data = yaml.safe_load(file)
        
        self.display_config_params()

    def display_config_params(self):
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
        
        # Clear widget and label references
        self.widgets = {}
        self.dimension_labels = {}
        self.dimension_widgets = {}

        # Create main container with two columns
        main_container = tk.Frame(self.scrollable_frame, bg='white')
        main_container.pack(fill="both", expand=True, padx=5, pady=5)

        # Use PanedWindow to create fixed-ratio columns
        paned_window = tk.PanedWindow(main_container, orient=tk.HORIZONTAL, bg='white', 
                                     sashwidth=4, sashrelief=tk.RAISED)
        paned_window.pack(fill="both", expand=True)

        # Create left and right column frames
        left_column = tk.Frame(paned_window, bg='white')
        right_column = tk.Frame(paned_window, bg='white')
        
        # Add frames to paned window
        paned_window.add(left_column, minsize=450, width=450)
        paned_window.add(right_column, minsize=450, width=450)
        
        # Prevent user from resizing panes
        paned_window.configure(sashrelief=tk.FLAT, sashwidth=1)

        # Define parameter groups for better organization
        param_groups = {
            "Input/Output Settings": ["input_file", "input_folder", "use_bulk", "rasterfile", "output_folder", "gpxfile"],
            "AOI Generation": ["generate_aoi", "aoi_name", "aoi_shape_type", "aoi_center_coords", "aoi_crs_epsg", "aoi_dimension1_mm", "aoi_dimension2_mm", "save_generated_shapefile", "save_geojson"],
            "Map Generation": [
                "generate_map",
                "map_filename", "map_dpi", "map_font_family",
                "map_font_size", "map_fontweight", "map_x_inverted", "map_keep_markers",
                "map_attempt_label_repositioning",
                "map_logo", "map_logo_width_cm", "map_logo_height_cm",
                "map_peaks", "map_peak_label_padding_cm",
                "map_peak_color", "map_peak_fontweight", "map_peak_label_italic",
                "map_mountain_huts", "map_mountain_hut_color", "map_mountain_hut_fontweight", "map_mountain_hut_label_italic",
                "map_settlements", "map_settlement_label_padding_cm",
                "map_settlement_color", "map_settlement_fontweight", "map_settlement_label_italic",
                "map_city", "map_town", "map_suburb", "map_village", "map_neighbourhood", "map_hamlet", "map_isolated_dwelling",
                "map_streets",
                "map_motorway", "map_trunk", "map_primary", "map_secondary", "map_tertiary", "map_residential", "map_service",
                "map_path", "map_footway", "map_track",
                "map_railways", "map_rail", "map_light_rail", "map_narrow_gauge",
                "map_waterways", "map_waterway_color",
                "map_waterway_river", "map_waterway_stream", "map_waterway_canal", "map_waterway_ditch", "map_waterway_drain",
                "map_water", "map_water_color",
                "map_water_lake", "map_water_reservoir", "map_water_river", "map_water_canal", "map_water_lock",
            ],
        }

        # Define which groups go in which column
        left_column_groups = ["Input/Output Settings", "AOI Generation",]
        right_column_groups = ["Map Generation"]

        # Track which parameters have been displayed
        displayed_params = set()

        # Process left column groups
        for group_name in left_column_groups:
            if group_name in param_groups:
                param_list = param_groups[group_name]
                self.create_group_frame(left_column, group_name, param_list, displayed_params)

        # Process right column groups
        for group_name in right_column_groups:
            if group_name in param_groups:
                param_list = param_groups[group_name]
                self.create_group_frame(right_column, group_name, param_list, displayed_params)

        # Display any remaining parameters that weren't in groups in the left column
        """ remaining_params = [k for k in self.config_data.keys() if k not in displayed_params]
        if remaining_params:
            self.create_other_params_frame(left_column, remaining_params) """

    def create_group_frame(self, parent, group_name, param_list, displayed_params):
        """Create a group frame with parameters"""
        # Check if any parameters in this group exist in config
        group_params = [p for p in param_list if p in self.config_data]
        if not group_params:
            return

        # Create group frame
        group_frame = tk.LabelFrame(parent, text=group_name, font=("Arial", 10, "bold"))
        group_frame.pack(fill="x", padx=5, pady=5)

        for key in group_params:
            value = self.config_data[key]
            displayed_params.add(key)
            self.create_parameter_widget(group_frame, key, value)

    def create_other_params_frame(self, parent, remaining_params):
        """Create frame for remaining parameters"""
        group_frame = tk.LabelFrame(parent, text="Other Parameters", font=("Arial", 10, "bold"))
        group_frame.pack(fill="x", padx=5, pady=5)

        for key in remaining_params:
            value = self.config_data[key]
            self.create_parameter_widget(group_frame, key, value)

    def create_parameter_widget(self, parent, key, value):
        """Create a widget for a single parameter"""
        # Create frame for each parameter
        param_frame = tk.Frame(parent)
        param_frame.pack(fill="x", padx=5, pady=2)

        # Label with tooltip
        label = tk.Label(param_frame, text=f"{key}:", width=18, anchor="w")
        label.pack(side="left")
        
        # Add tooltip if description exists
        if key in PARAMETER_DESCRIPTIONS:
            ToolTip(label, PARAMETER_DESCRIPTIONS[key])

        # Handle different parameter types
        if key == "input_file":
            self.create_file_selector(param_frame, key, value, "Select Input File", [("Shapefile", "*.shp"), ("GeoJSON", "*.geojson"), ("All files", "*.*")])
        elif key == "rasterfile":
            self.create_file_selector(param_frame, key, value, "Select Raster File", [("TIFF files", "*.tif"), ("All files", "*.*")])
        elif key == "gpxfile":
            self.create_file_selector(param_frame, key, value, "Select GPX File", [("GPX files", "*.gpx"), ("All files", "*.*")])
        elif key == "input_folder" and self.config_data.get("use_bulk", False):
            self.create_folder_selector(param_frame, key, value, "Select Input Folder")
        elif key == "input_folder" and not self.config_data.get("use_bulk", False):
            # Show disabled folder selector when use_bulk is False
            folder_frame = tk.Frame(param_frame)
            folder_frame.pack(side="left", fill="x", expand=True)
            entry = tk.Entry(folder_frame, state="disabled")
            entry.insert(0, str(value))
            entry.pack(side="left", fill="x", expand=True)
            tk.Label(folder_frame, text="(Enable 'use_bulk' to edit)", fg="gray").pack(side="left", padx=(5, 0))
        elif key == "output_folder":
            self.create_folder_selector(param_frame, key, value, "Select Output Folder")
        elif key == "dem_type":
            # Dropdown for DEM type selection
            dem_var = tk.StringVar(value=str(value) if value else "COP30")
            dem_combo = ttk.Combobox(param_frame, textvariable=dem_var, 
                                    values=["COP30", "NASADEM", "SRTMGL1"], 
                                    state="readonly", width=23)
            dem_combo.pack(side="left", fill="x", expand=True)
            dem_var.trace_add("write", lambda *args, k=key, v=dem_var: self.update_config(k, v.get()))
        elif key == "aoi_shape_type":
            # Dropdown for AOI shape type selection with callback to update dimension labels
            shape_var = tk.StringVar(value=str(value) if value else "circle")
            shape_combo = ttk.Combobox(param_frame, textvariable=shape_var, 
                                      values=["circle", "square", "rectangle", "hexagon"], 
                                      state="readonly", width=23)
            shape_combo.pack(side="left", fill="x", expand=True)
            def on_shape_change(*args):
                self.update_config(key, shape_var.get())
                self.update_dimension_labels(shape_var.get())
            shape_var.trace_add("write", on_shape_change)
        elif key == "aoi_dimension1_mm":
            # Create label with dynamic text based on shape type
            shape_type = self.config_data.get('aoi_shape_type', 'circle')
            label_text = self.get_dimension1_label(shape_type)
            label.config(text=label_text)
            self.dimension_labels['dimension1'] = label
            
            entry = tk.Entry(param_frame, width=25)
            entry.insert(0, str(value))
            entry.pack(side="left", fill="x", expand=True)
            entry.bind("<FocusOut>", lambda e, k=key: self.update_config(k, e.widget.get()))
        elif key == "aoi_dimension2_mm":
            # Create label with dynamic text based on shape type
            shape_type = self.config_data.get('aoi_shape_type', 'circle')
            label_text = self.get_dimension2_label(shape_type)
            label.config(text=label_text)
            self.dimension_labels['dimension2'] = label
            
            # Create entry widget (always create it, but enable/disable based on shape)
            entry = tk.Entry(param_frame, width=25)
            entry.insert(0, str(value))
            entry.pack(side="left", fill="x", expand=True)
            entry.bind("<FocusOut>", lambda e, k=key: self.update_config(k, e.widget.get()))
            
            # Create helper label
            helper_label = tk.Label(param_frame, text="(only for rectangle)", fg="gray", font=("Arial", 8))
            
            # Set initial state based on shape type
            if shape_type == 'rectangle':
                entry.config(state='normal')
                # Don't pack helper_label for rectangle
            else:
                entry.config(state='disabled')
                helper_label.pack(side="left", padx=(5, 0))
            
            # Store references for dynamic updates
            self.dimension_widgets['dimension2'] = {
                'entry': entry,
                'helper_label': helper_label
            }
        elif key == "height_scale" and self.config_data.get("variable_base_height", False):
            entry = tk.Entry(param_frame, width=25)
            entry.insert(0, str(value))
            entry.pack(side="left", fill="x", expand=True)
            entry.bind("<FocusOut>", lambda e, k=key: self.update_config(k, e.widget.get()))
        elif key == "height_scale" and not self.config_data.get("variable_base_height", False):
            # Show disabled height_scale when variable_base_height is False
            height_scale_frame = tk.Frame(param_frame)
            height_scale_frame.pack(side="left", fill="x", expand=True)
            entry = tk.Entry(height_scale_frame, state="disabled")
            entry.insert(0, str(value))
            entry.pack(side="left", fill="x", expand=True)
            tk.Label(height_scale_frame, text="(Enable 'variable_base_height' to edit)", fg="gray").pack(side="left", padx=(5, 0))
        elif isinstance(value, bool):
            var = tk.BooleanVar(value=value)
            checkbox = tk.Checkbutton(param_frame, variable=var)
            checkbox.pack(side="left")
            var.trace_add("write", lambda *args, k=key, v=var: self.on_config_change(k, v.get()))
        elif isinstance(value, list):
            entry = tk.Entry(param_frame, width=25)
            entry.insert(0, str(value))
            entry.pack(side="left", fill="x", expand=True)
            entry.bind("<FocusOut>", lambda e, k=key: self.update_config(k, e.widget.get()))
        else:
            entry = tk.Entry(param_frame, width=25)
            entry.insert(0, str(value))
            entry.pack(side="left", fill="x", expand=True)
            entry.bind("<FocusOut>", lambda e, k=key: self.update_config(k, e.widget.get()))
        

    def create_file_selector(self, parent, key, value, title="Select File", filetypes=None):
        """Create a file selector with browse button for file parameters"""
        if filetypes is None:
            filetypes = [("All files", "*.*")]
            
        file_frame = tk.Frame(parent)
        file_frame.pack(side="left", fill="x", expand=True)
        
        entry = tk.Entry(file_frame)
        entry.insert(0, str(value))
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<FocusOut>", lambda e, k=key: self.update_config(k, e.widget.get()))
        
        # Store widget reference
        self.widgets[key] = entry
        
        def browse_file():
            # Determine initial directory based on file type
            if key == "input_file":
                # For input_file, check if we're in single file mode (not bulk)
                if not self.config_data.get("use_bulk", False):
                    # In single file mode, start from inputs folder but store relative to project root
                    initial_dir = os.path.join(os.getcwd(), "inputs")
                else:
                    initial_dir = os.path.join(os.getcwd(), "inputs")
            elif key == "gpxfile":
                initial_dir = os.path.join(os.getcwd(), "inputs")
            elif key == "rasterfile":
                initial_dir = os.getcwd()  # Raster files are typically in the root
            else:
                initial_dir = os.getcwd()
                
            if not os.path.exists(initial_dir):
                initial_dir = os.getcwd()
            
            filename = filedialog.askopenfilename(
                title=title,
                initialdir=initial_dir,
                filetypes=filetypes
            )
            if filename:
                # Convert to relative path if it's within the project
                try:
                    rel_path = os.path.relpath(filename, os.getcwd())
                    if not rel_path.startswith(".."):
                        filename = rel_path
                except:
                    pass
                entry.delete(0, tk.END)
                entry.insert(0, filename)
                self.update_config(key, filename)
        
        browse_btn = tk.Button(file_frame, text="Browse...", command=browse_file)
        browse_btn.pack(side="right", padx=(5, 0))

    def create_folder_selector(self, parent, key, value, title="Select Folder"):
        """Create a folder selector with browse button for folder parameters"""
        folder_frame = tk.Frame(parent)
        folder_frame.pack(side="left", fill="x", expand=True)
        
        entry = tk.Entry(folder_frame)
        entry.insert(0, str(value))
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<FocusOut>", lambda e, k=key: self.update_config(k, e.widget.get()))
        
        def browse_folder():
            # Determine initial directory based on folder type
            if key == "input_folder":
                initial_dir = os.path.join(os.getcwd(), "inputs")
            elif key == "output_folder":
                initial_dir = os.path.join(os.getcwd(), "outputs")
            else:
                initial_dir = os.getcwd()
                
            if not os.path.exists(initial_dir):
                initial_dir = os.getcwd()
            
            # Use askdirectory specifically for folder selection only
            foldername = filedialog.askdirectory(
                title=title,
                initialdir=initial_dir
            )
            if foldername:
                # Convert to relative path if it's within the project
                try:
                    rel_path = os.path.relpath(foldername, os.getcwd())
                    if not rel_path.startswith(".."):
                        foldername = rel_path
                except:
                    pass
                entry.delete(0, tk.END)
                entry.insert(0, foldername)
                self.update_config(key, foldername)
        
        browse_btn = tk.Button(folder_frame, text="Browse...", command=browse_folder)
        browse_btn.pack(side="right", padx=(5, 0))

    def on_config_change(self, key, value):
        """Handle configuration changes with special logic for use_bulk and variable_base_height"""
        self.update_config(key, value)
        
        # If use_bulk changed, refresh the display to show/hide input_folder appropriately
        # If variable_base_height changed, refresh the display to show/hide height_scale appropriately
        if key == "use_bulk" or key == "variable_base_height":
            self.display_config_params()

    def update_config(self, key, value):
        try:
            # Convert the value to the appropriate type
            if isinstance(self.config_data[key], bool):
                self.config_data[key] = bool(value)
            elif isinstance(self.config_data[key], int):
                self.config_data[key] = int(value)
            elif isinstance(self.config_data[key], float):
                self.config_data[key] = float(value)
            elif isinstance(self.config_data[key], list):
                # Convert string representation of list to actual list of floats
                self.config_data[key] = [float(v.strip()) for v in value.strip('[]').split(',')]
            else:
                self.config_data[key] = value
        except ValueError:
            self.config_data[key] = value

    def generate_data(self):
        config_filename = self.config_file.get()
        if not config_filename:
            show_error("Error", "No config file selected.")
            return
        
        # Check if we're generating an AOI
        generate_aoi = (not self.config_data.get('input_file') or self.config_data['input_file'].strip() == '') and \
                       self.config_data.get('generate_aoi', False)
        
        # Check if input_file is empty and generate_aoi is enabled
        if generate_aoi:
            try:                
                # Parse coordinates from comma-separated string
                coords_str = self.config_data.get('aoi_center_coords', '47.2692, 11.4041')
                coords = coords_str.split(',')
                center_lat = float(coords[0].strip())
                center_lon = float(coords[1].strip())
                
                # Get other AOI parameters from config
                aoi_name = self.config_data.get('aoi_name', 'generated_aoi')
                output_crs_epsg = self.config_data.get('aoi_crs_epsg', None)
                shape_type = self.config_data.get('aoi_shape_type', 'circle')
                scale = self.config_data.get('scale', 50000)
                dimension1_mm = self.config_data.get('aoi_dimension1_mm', 100)
                dimension2_mm = self.config_data.get('aoi_dimension2_mm', None) if shape_type == 'rectangle' else None
                save_shapefile = self.config_data.get('save_generated_shapefile', False)
                prefer_etrs89 = self.config_data.get('prefer_etrs89_in_europe', False)
                save_geojson = self.config_data.get('save_geojson', False)
                
                # Handle cases where aoi_crs_epsg might be None, empty string, or the string "None"
                if output_crs_epsg is None or output_crs_epsg == '' or str(output_crs_epsg).strip().lower() == 'none':
                    output_crs_epsg = None
                
                # Automatically determine UTM zone if no CRS specified
                if output_crs_epsg is None:
                    print("No CRS specified, automatically determining optimal UTM zone...")
                    
                    # Import UTM selection functions
                    from utm_finder import (
                        get_utm_zone_from_lon,
                        is_in_norway_special_zone,
                        is_in_svalbard_special_zone,
                        _get_epsg_from_zone,
                        _is_in_europe
                    )
                    
                    # Check for special zones
                    special_zone = is_in_svalbard_special_zone(center_lat, center_lon)
                    if special_zone:
                        utm_zone = special_zone
                        print(f"  → Svalbard special zone detected: UTM Zone {utm_zone}")
                    else:
                        special_zone = is_in_norway_special_zone(center_lat, center_lon)
                        if special_zone:
                            utm_zone = special_zone
                            print(f"  → Norway special zone detected: UTM Zone {utm_zone}")
                        else:
                            # Standard UTM zone calculation
                            utm_zone = get_utm_zone_from_lon(center_lon)
                            print(f"  → Standard UTM zone: {utm_zone}")
                    
                    # Determine hemisphere and EPSG
                    hemisphere = 'north' if center_lat >= 0 else 'south'
                    output_crs_epsg = _get_epsg_from_zone(utm_zone, hemisphere, prefer_etrs89, center_lat, center_lon)
                    
                    zone_label = f"UTM Zone {utm_zone}{hemisphere[0].upper()}"
                    if prefer_etrs89 and _is_in_europe(center_lat, center_lon):
                        zone_label += " (ETRS89)"
                    
                    print(f"  → Selected: EPSG:{output_crs_epsg} ({zone_label})")
                
                # Note: We don't add aoi_name to output_folder here because generate_data.py
                # will automatically use the shapefile's base name as a subfolder.
                # Since the shapefile is named {aoi_name}.shp, the final structure will be:
                # outputs/{output_folder}/{aoi_name}/ngc/ and /stl/
                
                # Generate output path for shapefile
                if save_shapefile:
                    output_file = os.path.join("inputs", f"{aoi_name}.shp")
                else:
                    # Create temporary file
                    temp_dir = tempfile.mkdtemp()
                    output_file = os.path.join(temp_dir, f"{aoi_name}.shp")
                
                # Generate shapefile (without GeoJSON initially)
                generate_shapefile(center_lon, center_lat, output_crs_epsg, dimension1_mm, 
                                 dimension2_mm, scale, output_file, shape_type, save_geojson=False)
                
                # Store the generated shapefile path for processing, but don't update config if it's a temp file
                generated_shapefile = output_file
                if save_shapefile:
                    # Only update config if we're saving the shapefile permanently
                    self.config_data['input_file'] = output_file
                    print(f"✓ Generated AOI shapefile (saved): {output_file}")
                else:
                    print(f"✓ Generated AOI shapefile (temporary): {output_file}")
                
                # Save GeoJSON to output folder if requested
                if save_geojson:
                    # Determine output folder path
                    base_output_folder = self.config_data.get('output_folder', 'outputs')
                    output_path = os.path.join(base_output_folder, aoi_name)
                    os.makedirs(output_path, exist_ok=True)
                    
                    # Generate GeoJSON directly in output folder
                    geojson_output_path = os.path.join(output_path, f"{aoi_name}.geojson")
                    
                    # Call generate_shapefile again just to create the GeoJSON
                    # (We pass a dummy path and only use the GeoJSON output)
                    temp_shp_for_geojson = os.path.join(output_path, f"{aoi_name}.shp")
                    generate_shapefile(center_lon, center_lat, output_crs_epsg, dimension1_mm, 
                                     dimension2_mm, scale, temp_shp_for_geojson, shape_type, save_geojson=True)
                    
                    # Remove the duplicate shapefile files we just created
                    for ext in ['.shp', '.shx', '.dbf', '.prj']:
                        temp_file = temp_shp_for_geojson.replace('.shp', ext)
                        if os.path.exists(temp_file):
                            os.remove(temp_file)
                    
                    print(f"✓ Generated GeoJSON (WGS84): {geojson_output_path}")
            except Exception as e:
                show_error("Error", f"Failed to generate AOI shapefile:\n{str(e)}")
                return
        else:
            # No AOI generation, use existing input_file
            generated_shapefile = None
        
        # Proceed with data generation
        # Create a copy of config for processing (don't modify the original)
        processing_config = self.config_data.copy()
        
        # If we generated a shapefile, use it for processing
        if generate_aoi and generated_shapefile:
            processing_config['input_file'] = generated_shapefile
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".yaml", mode='w') as temp_config_file:
            yaml.safe_dump(processing_config, temp_config_file)
            temp_config_path = temp_config_file.name
        
        # Run map generation as subprocess
        if self.config_data.get('use_bulk', False):
            # In bulk mode, generate_map.py handles all files internally
            print("Generating maps in bulk mode...")
            input_folder = os.path.abspath(self.config_data.get('input_folder'))
            geo_files = [f for f in os.listdir(input_folder) if f.endswith(('.shp', '.geojson'))]

            if not geo_files:
                show_info("Info", "No shapefiles or GeoJSON files found in the input folder for map generation.")
                return
            
            print(f"Found {len(geo_files)} files for map generation.")
            
            for i, file in enumerate(geo_files):
                print(f"Generating map {i+1}/{len(geo_files)} for: {file}")
                self.config_data['input_file'] = os.path.join(input_folder, file)
                self.config_data['map_filename'] = f"{os.path.splitext(file)[0]}_map.png"
                with tempfile.NamedTemporaryFile(delete=False, suffix=".yaml", mode='w') as temp_config_file:
                    yaml.safe_dump(self.config_data, temp_config_file)
                    temp_config_path = temp_config_file.name
                result = subprocess.run([sys.executable, "src/generate_map.py", "--config", temp_config_path])
        else:
            result = subprocess.run([sys.executable, "src/generate_map.py", "--config", temp_config_path])
        
        os.remove(temp_config_path)     
        
        # Show completion message with link to output folder
        if result.returncode == 0:
            output_folder = self.config_data.get('output_folder', 'outputs')
            
            # If we generated an AOI, the output path includes the aoi_name from the shapefile
            if generate_aoi:
                aoi_name = self.config_data.get('aoi_name', 'generated_aoi')
                output_path = os.path.abspath(os.path.join(output_folder, aoi_name))
            else:
                # For regular processing, generate_data.py also adds the shapefile base name
                # So we need to get the input file name
                input_file = self.config_data.get('input_file', '')
                if input_file and not self.config_data.get('use_bulk', False):
                    file_base_name = os.path.splitext(os.path.basename(input_file))[0]
                    output_path = os.path.abspath(os.path.join(output_folder, file_base_name))
                else:
                    output_path = os.path.abspath(os.path.join(output_folder))
            
            if os.path.exists(output_path):
                message = f"✓ Data generation complete!\n\nOutput folder:\n{output_path}"
                show_info("Success", message)
                print(f"\n{'='*80}")
                print(f"✓ Processing complete!")
                print(f"Output folder: {output_path}")
                print(f"{'='*80}\n")


    def open_save_dialog(self):
        self.save_dialog = tk.Toplevel(self)
        self.save_dialog.title("Save Config As")
        self.save_dialog.geometry("300x150")

        tk.Label(self.save_dialog, text="Enter Config File Name:").pack(pady=5)
        self.save_filename_entry = tk.Entry(self.save_dialog)
        self.save_filename_entry.pack(pady=5)

        tk.Button(self.save_dialog, text="Save", command=self.save_config_as).pack(side="left", padx=10, pady=10)
        tk.Button(self.save_dialog, text="Cancel", command=self.save_dialog.destroy).pack(side="right", padx=10, pady=10)

    def save_config_as(self):
        config_filename = self.save_filename_entry.get()
        if not config_filename:
            show_error("Error", "No config file name provided.")
            return
        if not config_filename.endswith('.yaml'):
            config_filename += '.yaml'
        config_path = os.path.join(self.config_folder, config_filename)
        with open(config_path, 'w') as file:
            yaml.safe_dump(self.config_data, file)
        show_info("Success", "Config file saved successfully.")
        self.save_dialog.destroy()

    def save_config(self):
        config_filename = self.config_file.get()
        if not config_filename:
            show_error("Error", "No config file selected.")
            return
        config_path = os.path.join(self.config_folder, config_filename)
        with open(config_path, 'w') as file:
            yaml.safe_dump(self.config_data, file)
        show_info("Success", "Config file saved successfully.")

if __name__ == "__main__":
    app = ConfigEditor()
    app.mainloop()
