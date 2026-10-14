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


portal_mode_ui = ts.Enums.PortalMode.AnyUserInterface
# need to specify target version e.g. "17.0", requires that TIA portal V17 is installed
version = "20.0"

portal = ts.attach_portal(portal_mode = portal_mode_ui, version = version)
    
project = portal.get_project()

plcs = project.get_plcs()
for plc in plcs: 
    print(plc.get_name())
    
plcs[0].open_device_editor()

sys.exit(0)