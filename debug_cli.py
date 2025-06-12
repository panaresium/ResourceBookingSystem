print("--- Minimal debug script: Phase 1 (Flask import) ---")
import traceback
try:
    import flask
    print(f"Successfully imported flask. Version: {flask.__version__}")
except Exception as e:
    print("--- EXCEPTION DURING FLASK IMPORT ---")
    print(f"Error type: {type(e)}")
    print(f"Error message: {str(e)}")
    traceback.print_exc()
    print("--- END OF FLASK IMPORT EXCEPTION ---")
print("--- Minimal debug script: Phase 1 finished ---")
