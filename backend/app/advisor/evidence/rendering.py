import re
from .contracts import Narrative

REF = re.compile(r'\{\{([A-Za-z0-9_]+)\}\}')
NUMBER_WORDS = re.compile(r'\b(zero|one|two|three|four|five|six|seven|eight|nine|ten|hundred|thousand|million|billion)\b', re.I)


def formatted(metric):
    value, unit = metric['value'], metric['definition']['unit']
    if value is None:
        return 'unavailable'
    if unit == 'USD':
        from decimal import Decimal
        amount = Decimal(value)
        return ('-' if amount < 0 else '') + '$' + f'{abs(amount):,.2f}'
    return value + ('%' if unit == '%' else '')


def render_answer(payload, evidence):
    answer = Narrative.model_validate(payload)
    output, references = [], []
    def replace(match):
        key = match.group(1)
        if key not in evidence['metrics']:
            raise ValueError('Unknown metric reference')
        references.append(key)
        return formatted(evidence['metrics'][key])
    for block in answer.blocks:
        if (block.text is None) == (block.ranking is None):
            raise ValueError('Each block must be text or a ranking')
        if block.text is not None:
            residue = REF.sub('', block.text)
            if re.search(r'\d|\{\{|\}\}', residue) or NUMBER_WORDS.search(residue):
                raise ValueError('All numerical claims must reference metrics')
            output.append(REF.sub(replace, block.text))
        else:
            ranked = evidence['rankings'].get(block.ranking)
            if ranked is None:
                raise ValueError('Unknown ranking reference')
            lines = [f"{ranked['group'].replace('_', ' ').title()} contributors ({ranked['measure'].replace('_', ' ')}):"]
            for row in ranked['rows']:
                parts = []
                for label, key in row['references'].items():
                    references.append(key)
                    parts.append(f"{label}: {formatted(evidence['metrics'][key])}")
                lines.append('- ' + row['id'] + ': ' + '; '.join(parts))
            output.append('\n'.join(lines))
    return '\n\n'.join(output), list(dict.fromkeys(references))
