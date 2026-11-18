"""Commercial exclusions must hold across Python, CLI and MCP interfaces."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import swforge


def test_withheld_implementations_are_not_importable():
    for name in ('blank','mechanical_review','drafting','drawing_facts','conformity',
                 'annotation_rules','process_rules','drawing_set','drawing_raster'):
        assert importlib.util.find_spec('swforge.'+name) is None
    for name in ('compute_blank','review_mechanical','BlankSpec','blank_validate'):
        assert not hasattr(swforge,name)


def test_paid_operations_are_not_invokable():
    from swforge.server import mcp
    scope=json.loads((Path(__file__).parents[1]/'COMMUNITY_SCOPE.json').read_text(encoding='utf8'))
    for name in scope['excluded_operations']:
        assert name not in mcp._gateway.registry
        assert mcp._gateway.invoke(name,{})['error']=='unregistered'
    assert len(mcp._gateway.registry)==scope['operation_count']


def test_matrix_exactly_matches_registered_community_operations():
    from swforge.server import mcp
    from swforge.capability_matrix import load_matrix
    rows=load_matrix()['capabilities']
    assert {r['id'] for r in rows}==set(mcp._gateway.registry)
    assert len(rows)==len({r['id'] for r in rows})


def test_cli_does_not_offer_withheld_commands():
    text=subprocess.check_output([sys.executable,'-X','utf8','-m','swforge.cli','--help'],encoding='utf8')
    for name in ('blank','mechanical-review','drafting-check','gb-conformity','raster-review'):
        assert '\n    '+name+' ' not in text


def test_legacy_public_operations_remain_available():
    # Public 1.7 operations are recorded as identifiers, without shipping private code.
    from swforge.server import mcp
    scope=json.loads((Path(__file__).parents[1]/'COMMUNITY_SCOPE.json').read_text(encoding='utf8'))
    assert set(scope['baseline_operations'])<=set(mcp._gateway.registry)
