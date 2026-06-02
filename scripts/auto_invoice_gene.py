import subprocess

def run_script(script_path):
    try:
        result = subprocess.run(['python', script_path], check=True, capture_output=True, text=True)
        print(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"Error running {script_path}:")
        print(e.stderr)

if __name__ == "__main__":
    scripts_to_run = [
        "f:\\.DATA-Analyst-Coures\\.shlomy_store\\full_project\\store_pipeline\\01_restore_backup.py",
        "f:\\.DATA-Analyst-Coures\\.shlomy_store\\full_project\\store_pipeline\\02_extract_load_03.py"
    ]
    
    for script in scripts_to_run:
        run_script(script)
    
    subprocess.run(['uv', 'run', 'dbt', 'run', '--target', 'prod'], check=True, capture_output=True, text=True)