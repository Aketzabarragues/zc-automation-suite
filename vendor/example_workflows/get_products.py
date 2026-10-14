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

bundles = ts.get_installed_bundles()
for bundle in bundles:
    print("---------------------------------------------------------------------------------------")
    print("Bundle ",bundle.get_title(), bundle.get_release())
    for product in bundle.get_products():
        print("product: ",product.get_name(), "release: ", product.get_release(), "version: ",product.get_version())
    print("---------------------------------------------------------------------------------------")


print("------------------------------------------------------------------------------------------------------------------")
print("------------------------------------------------------------------------------------------------------------------")
print("------------------------------------------------------------------------------------------------------------------")
print("------------------------------------------GET INSTALLED PRODUCTS--------------------------------------------------")
print("------------------------------------------------------------------------------------------------------------------")
print("------------------------------------------------------------------------------------------------------------------")
print("------------------------------------------------------------------------------------------------------------------")
products = ts.get_installed_products()
for product in products:
     print("product: ",product.get_name(), "version: ",product.get_version())
    

sys.exit(0)