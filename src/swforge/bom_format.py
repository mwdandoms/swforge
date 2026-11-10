"""Basic BOM column and numbering checks."""
import re
def validate_bom_format(rows, columns, header_position):
    expected = ['序号', '代号', '名称', '数量', '材料', '备注']
    findings = []
    if columns != expected:
        findings.append('column_order')
    if header_position != 2:
        findings.append('bottom_header')
    numbers = []
    for row in reversed(rows[:-1]):
        try:
            numbers.append(int(re.sub('<[^>]*>', '', row['cells'][0]).strip()))
        except (ValueError, IndexError):
            findings.append('invalid_item_number')
    if numbers != list(range(1, len(numbers) + 1)):
        findings.append('bottom_up_continuous_numbering')
    return dict(verified=True, passed=not findings, findings=findings, profile='six-column GB-oriented BOM')
