import os
from typing import Dict

class ScenarioBuilder:
    def __init__(self, templates_dir: str = "app/scenarios"):
        self.templates_dir = templates_dir

    def build_isolated_ini(self, sandboxed_dir: str, scenario_name: str, overrides: Dict[str, float]) -> str:
        """
        Parses the robust standards-based configuration templates and maps high-level
        agent intent variables directly to deep internal Simu5G configuration keys.
        """
        clean_name = scenario_name.replace(".ini", "")
        template_file_path = os.path.join(self.templates_dir, f"{clean_name}.ini")
        
        if os.path.exists(template_file_path):
            with open(template_file_path, "r") as f:
                base_content = f.read()
        else:
            raise FileNotFoundError(f"Reference standard profile not found at: {template_file_path}")

        # Explicit Structural Parameter Mapping Matrix
        structural_mappings = {
            "txPower_dBm": {
                "normal_operation": "*.gNodeB.cellularNic.phy.txPower",
                "handover_failure": "*.gNodeB[*].cellularNic.phy.txPower",
                "energy_optimization": "*.macroGNodeB.cellularNic.phy.txPower"
            },
            "handoverMargin_dB": {
                "normal_operation": "*.gNodeB.cellularNic.rrc.handoverMargin",
                "handover_failure": "*.gNodeB[*].cellularNic.rrc.handoverMargin",
                "energy_optimization": "*.macroGNodeB.cellularNic.rrc.handoverMargin"
            },
            "timeToTrigger_ms": {
                "normal_operation": "*.gNodeB.cellularNic.rrc.timeToTrigger",
                "handover_failure": "*.gNodeB[*].cellularNic.rrc.timeToTrigger",
                "energy_optimization": "*.macroGNodeB.cellularNic.rrc.timeToTrigger"
            }
        }

        base_content += "\n# =========================================================================\n"
        base_content += "# DYNAMIC CLOSED-LOOP REMEDIATION OVERRIDES (AGENT GENERATED)\n"
        base_content += "# =========================================================================\n"
        
        # Explicit evaluation of O-RAN state parameters
        if clean_name == "energy_optimization" and "sleepModeActive" in overrides:
            flag_value = "true" if overrides["sleepModeActive"] == 1.0 else "false"
            base_content += f"*.microGNodeB[*].energyConsumptionModel.sleepModeActive = {flag_value}\n"

        # Inject standard-compliant text assignments
        for param_key, param_value in overrides.items():
            if param_key in structural_mappings and clean_name in structural_mappings[param_key]:
                module_path = structural_mappings[param_key][clean_name]
                unit = "dBm" if "txPower" in param_key else ("ms" if "timeToTrigger" in param_key else "dB")
                base_content += f"{module_path} = {param_value}{unit}\n"

        # Ensure the sandboxed directory folder physically exists
        os.makedirs(sandboxed_dir, exist_ok=True)

        # Output the executable file directly to the temporary workspace sandbox path
        output_path = os.path.join(sandboxed_dir, "omnetpp.ini")
        with open(output_path, "w") as f:
            f.write(base_content)
            
        return output_path
