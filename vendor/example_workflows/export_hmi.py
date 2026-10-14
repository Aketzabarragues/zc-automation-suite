import os
import sys

# Use TIA Scripting via file import (Only if TIA Scripting is not installed as package)
# need to set a global environment variable “TIA_SCRIPTING” with path containing TIA Scripting binaries
if os.getenv('TIA_SCRIPTING')  == None:
    # if TIA_SCRIPTING global environment variable is not set
    # set local variable with the path to TIA Scripting binaries
    tia_scripting_directory = "C:\\your\\path\\to\\tia-scripting-python"
    sys.path.append(tia_scripting_directory)
else:
    # TIA_SCRIPTING global environment variable is set and will be used for import
    sys.path.append(os.getenv('TIA_SCRIPTING'))

try:
    # import TIA Scripting binaries
    # if TIA Scripting is installed as package, global environment variable will be ignored
    import siemens_tia_scripting as ts
except ImportError:
    # you will run into ImportError also if you are using Python version which is not 3.12.X
    print("siemens_tia_scripting could not be found")
    sys.exit(0)

portal_mode_ui = True
keep_tia_portal = False
# example values for directories
project_file_path = "D:\\TiaScripting\\HMI_ExportAll\\HMI_ExportAll.ap20"
export_target_dir = "D:\\TiaScripting\\Export"
keep_folder_structure = True
# need to specify target version e.g. "17.0", requires that TIA portal V17 is installed
version = "20.0"

if portal_mode_ui == True:
    portal = ts.open_portal(ts.Enums.PortalMode.WithGraphicalUserInterface, version = version)
    print("- open/attach tia portal with ui")
else:
    portal = ts.open_portal(ts.Enums.PortalMode.WithoutGraphicalUserInterface, version = version)
    print("- open/attach tia portal without ui")
    
project = portal.open_project(project_file_path = project_file_path, server_project_view = False)
print("- open project")
    
hmis = project.get_hmis()
for hmi in hmis:
    if hmi.get_hmi_type() == "Comfort":
        comfort_target_dir = export_target_dir + "_Comfort"
        # Tag Tables
        for table in hmi.get_hmi_tag_tables():
            table.export(comfort_target_dir + r"\TagTables", keep_folder_structure= True)
        # Screens
        for screen in hmi.get_screens():
            screen.export(comfort_target_dir + r"\Screens", keep_folder_structure= True)
        # Text Lists
        for text_list in hmi.get_text_lists():
            text_list.export(comfort_target_dir + r"\TextLists")
        # Scripts
        for script in hmi.get_scripts():
            script.export(comfort_target_dir + r"\Scripts", keep_folder_structure= True)
        # Connections
        for conn in hmi.get_connections():
            conn.export(comfort_target_dir + r"\Connections")
        # Cycles
        for cycle in hmi.get_cycles():
            cycle.export(comfort_target_dir + r"\Cycles")
        # Graphic Lists
        for glist in hmi.get_graphic_lists():
            glist.export(comfort_target_dir + r"\GraphicLists")
        # Global Screen Elements
        global_elements = hmi.get_global_screen_elements()
        if global_elements:
            global_elements.export(comfort_target_dir + r"\GlobalElements")
        # Screen Overview
        screen_overview = hmi.get_screen_overview()
        if screen_overview:
            screen_overview.export(comfort_target_dir + r"\ScreenOverview")
        # Slide-In Screens
        for slidein in hmi.get_slide_in_screens():
            slidein.export(comfort_target_dir + r"\SlideInScreens", keep_folder_structure= True)
    if hmi.get_hmi_type() == "Unified":
        unified_target_dir = export_target_dir + "_Unified"
        # Scripts
        for script in hmi.get_scripts():
            script.export(unified_target_dir + r"\Scripts", export_format=ts.Enums.ExportFormats.SimaticSD)
        # Tag Tables
        for table in hmi.get_hmi_tag_tables():
            table.export(unified_target_dir + r"\TagTables", export_format=ts.Enums.ExportFormats.SimaticSD, keep_folder_structure= True)
        for text_list in hmi.get_text_lists():
            text_list.export(unified_target_dir + r"\TextLists", export_format=ts.Enums.ExportFormats.SimaticSD, keep_folder_structure= True)
        
            
if keep_tia_portal == "False":
    portal.close_portal()
    print("- close tia portal")

if keep_tia_portal == "True":
    print("- keep tia portal")
    

sys.exit(0) 