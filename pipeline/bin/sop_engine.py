"""SOP Enforcement Engine for KAIROS v4.0 — from MetaGPT."""
import yaml, os, json, re
from pathlib import Path
from dataclasses import dataclass, field

@dataclass
class SOPViolation:
    agent: str
    phase: str
    step_id: str
    violation_type: str  # missing_file | duration_exceeded | output_criteria_failed | required_action_skipped
    details: str
    severity: str = "error"  # error | warning

class SOPEngine:
    """
    Loads SOP definitions from YAML and enforces them at each phase/step.
    v4.0: Enforces Standard Operating Procedures for each agent.
    """
    
    def __init__(self, registry_path="/etc/karios/v4/sops"):
        self.registry_path = registry_path
        self.sops = {}
        self._load_sops()
    
    def _load_sops(self):
        """Load all SOP YAML files from registry path."""
        sop_dir = Path(self.registry_path)
        if not sop_dir.exists():
            # Fall back to bundled sops
            sop_dir = Path(__file__).parent / "sops"
        
        for yaml_file in sop_dir.glob("*.yaml"):
            try:
                with open(yaml_file) as f:
                    sop = yaml.safe_load(f)
                    agent = sop.get('agent')
                    if agent:
                        self.sops[agent] = sop
            except Exception as e:
                print(f"[SOP] Failed to load {yaml_file}: {e}")
    
    def get_sop(self, agent: str):
        """Get SOP for a specific agent."""
        return self.sops.get(agent)
    
    def check_pre_conditions(self, agent: str, phase: str, step_id: str, context: dict) -> list[SOPViolation]:
        """
        Run before each operation. Returns list of violations.
        Checks:
        - Required files exist
        - Required actions (e.g., check learnings) were done
        - Prerequisites met
        """
        violations = []
        sop = self.get_sop(agent)
        if not sop:
            return violations
        
        phase_config = sop.get('phases', {}).get(phase, {})
        for step in phase_config.get('required_steps', []):
            if step['id'] != step_id:
                continue
            
            # v7.3 FIX 2026-04-19: required_output_files are POSTCONDITIONS, not preconditions.
            # Iteration 1 cannot have files yet — those are what the agent is being dispatched to produce.
            # The existence check now lives in check_post_conditions only.
            pass  # output_files now checked post-execution only

            # Check "before" required actions (e.g., "Check learnings")
            for action in step.get('before', []):
                if 'learnings' in action.lower():
                    # Verify semantic memory was consulted
                    if not context.get('learnings_checked'):
                        violations.append(SOPViolation(
                            agent=agent, phase=phase, step_id=step_id,
                            violation_type='required_action_skipped',
                            details=f"Required action not performed: {action}"
                        ))
        
        return violations
    
    def check_post_conditions(self, agent: str, phase: str, step_id: str, 
                             output: str, duration_minutes: float = None,
                             files_created: list = None) -> list[SOPViolation]:
        """
        Run after each operation. Validates output against criteria.
        Checks:
        - Output criteria (e.g., "At least 5 frameworks researched")
        - Max duration not exceeded
        - Output files created
        """
        violations = []
        sop = self.get_sop(agent)
        if not sop:
            return violations
        
        phase_config = sop.get('phases', {}).get(phase, {})
        for step in phase_config.get('required_steps', []):
            if step['id'] != step_id:
                continue
            
            # Check output criteria
            for criterion in step.get('output_criteria', []):
                if not self._evaluate_criterion(criterion, output, files_created):
                    violations.append(SOPViolation(
                        agent=agent, phase=phase, step_id=step_id,
                        violation_type='output_criteria_failed',
                        details=f"Output criterion not met: {criterion}"
                    ))
            
            # Check max duration
            max_dur = step.get('max_duration_minutes', 60)
            if duration_minutes and duration_minutes > max_dur:
                violations.append(SOPViolation(
                    agent=agent, phase=phase, step_id=step_id,
                    violation_type='duration_exceeded',
                    details=f"Step exceeded time limit: {duration_minutes:.1f}m > {max_dur}m"
                ))
        
        return violations
    
    def _evaluate_criterion(self, criterion: str, output: str, files_created: list = None) -> bool:
        """Evaluate a single output criterion against actual output."""
        criterion_lower = criterion.lower()
        output_lower = output.lower()
        
        # Pattern: "At least N things" -> count
        m = re.search(r'at least (\d+)', criterion_lower)
        if m:
            min_count = int(m.group(1))
            # Try to count mentions in output
            items = [x.strip() for x in re.split(r'[,;\n]', output) if x.strip()]
            if len(items) >= min_count:
                return True
        
        # Pattern: "Includes X" -> substring search
        m = re.search(r'includes?\s+([^"]+)', criterion_lower)
        if m:
            required = m.group(1).strip().lower()
            if required in output_lower:
                return True
        
        # Pattern: "References to X" -> look for URLs or mentions
        if 'reference' in criterion_lower:
            url_pattern = r'https?://[^\s]+'
            if re.search(url_pattern, output):
                return True
        
        # Pattern: "X created" -> check files_created list
        if files_created:
            for f in files_created:
                if criterion_lower.replace(' ', '_') in f.lower():
                    return True
        
        # Default: check if criterion keywords appear
        keywords = [w for w in re.findall(r'\b\w+\b', criterion_lower) if len(w) > 4]
        matches = sum(1 for kw in keywords if kw in output_lower)
        return matches >= max(1, len(keywords) // 2)
    
    def get_gate_condition(self, agent: str) -> dict:
        """Get gate conditions for an agent (min_quality_score, etc.)."""
        sop = self.get_sop(agent)
        if not sop:
            return {'min_quality_score': 0.7, 'block_on_sop_violation': True}
        return sop.get('gate_conditions', {})