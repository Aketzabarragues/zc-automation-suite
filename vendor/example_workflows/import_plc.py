import os
import sys
import siemens_tia_scripting as ts


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
project_file_path = "D:\\TiaScripting\\PLC_ImportAll\\PLC_ImportAll.ap17"
import_root_dir = "D:\\TiaScripting\\Export"
version = "20.0"

project = ts.open_attach_project(project_file_path)
plcs = project.get_plcs()
for plc in plcs:
    plc_name = plc.get_name()
    plc_import_dir = import_root_dir + "\\" + plc_name

    # Import all user data types
    udts_import_dir = plc_import_dir + "\\PLC data types"
    if os.path.isdir(udts_import_dir):
        plc.import_data_types(import_root_directory=udts_import_dir)

    # Import all PLC tag tables
    tag_tables_import_dir = plc_import_dir + "\\PLC tags"
    if os.path.isdir(tag_tables_import_dir):
        plc.import_plc_tags(import_root_directory=tag_tables_import_dir)

    # Import all software units
    software_units_dir = plc_import_dir + "\\Software units"
    if os.path.isdir(software_units_dir):
        for su_name in os.listdir(software_units_dir):
            su_dir = software_units_dir + "\\" + su_name
            if not os.path.isdir(su_dir):
                continue
            new_software_unit = plc.create_software_unit(name = su_name)
            config_file = su_dir + "\\SoftwareUnitConfiguration.xml"
            if os.path.isfile(config_file):
                new_software_unit.import_configuration(import_file_path=config_file)
            program_blocks_dir = su_dir + "\\Program blocks"
            if os.path.isdir(program_blocks_dir):
                new_software_unit.import_blocks(import_root_directory=program_blocks_dir)

sys.exit(0)