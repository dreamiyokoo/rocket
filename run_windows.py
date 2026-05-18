import os
import subprocess
import re

windows = [20, 30, 40, 60, 80]
csv_path = os.path.abspath("docs/rounds_export_ml.csv")
script_path = "scripts/ml_model.py"

with open(script_path, "r") as f:
    orig_content = f.read()

print("| WINDOW | Accuracy | AUC | Blue F1 | Green F1 | Yellow F1 | Red F1 |")
print("|---|---|---|---|---|---|---|")

def extract(text):
    results = {}
    
    # Accuracy line in multi-class report
    acc_match = re.search(r'accuracy\s+([\d\.]+)', text)
    results['accuracy'] = acc_match.group(1) if acc_match else "N/A"
    
    # AUC: 0.XXXX
    auc_match = re.search(r'AUC: ([\d\.]+)', text)
    results['auc'] = auc_match.group(1) if auc_match else "N/A"
    
    # F1 scores
    # Example line: "    Blue(≤2x)       0.54      0.35      0.42       997"
    blue = re.search(r'Blue\(≤2x\)\s+[\d\.]+\s+[\d\.]+\s+([\d\.]+)', text)
    green = re.search(r'Green\(2-5x\)\s+[\d\.]+\s+[\d\.]+\s+([\d\.]+)', text)
    yellow = re.search(r'Yellow\(5-10x\)\s+[\d\.]+\s+[\d\.]+\s+([\d\.]+)', text)
    red = re.search(r'Red\(>10x\)\s+[\d\.]+\s+[\d\.]+\s+([\d\.]+)', text)
    
    results['blue'] = blue.group(1) if blue else "N/A"
    results['green'] = green.group(1) if green else "N/A"
    results['yellow'] = yellow.group(1) if yellow else "N/A"
    results['red'] = red.group(1) if red else "N/A"
    
    return results

for w in windows:
    # Use full path for csv because script is moved to /tmp
    new_content = re.sub(r'WINDOW = \d+', f'WINDOW = {w}', orig_content)
    tmp_path = f"/tmp/ml_model_window_{w}.py"
    with open(tmp_path, "w") as f:
        f.write(new_content)
    
    res = subprocess.run(["python3", tmp_path, "--csv", csv_path], capture_output=True, text=True)
    metrics = extract(res.stdout)
    
    print(f"| {w} | {metrics['accuracy']} | {metrics['auc']} | {metrics['blue']} | {metrics['green']} | {metrics['yellow']} | {metrics['red']} |")
