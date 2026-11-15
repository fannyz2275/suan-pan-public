"""Pending analysis is workflow state, not long-term preference memory."""
UPLOAD_REQUIREMENTS = {'aligned_wealth', 'complete_cost_basis'}


def readiness(pending, availability, data_version):
    missing = [r for r in pending['requirements'] if not availability.get(r, False)]
    return {'ready':pending['status'] == 'waiting' and data_version != pending['data_version'] and not missing,
            'missing':missing, 'upload_action':'upload_statements' if set(missing) & UPLOAD_REQUIREMENTS else None}


def claim_state(status):
    if status == 'complete': return 'cached'
    if status == 'waiting': return 'run'
    raise ValueError('Analysis already running or requires explicit recovery')
