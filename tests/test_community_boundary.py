from pathlib import Path
import importlib.util
import subprocess
import sys
import swforge


def test_private_implementations_are_absent():
    for module in ('conformity','drawing_raster','drawing_set','process_rules','annotation_rules'):
        assert importlib.util.find_spec('swforge.'+module) is None
    assert not hasattr(swforge,'check_gb_conformity')
    assert not hasattr(swforge,'apply_process_rules')


def test_private_gateway_operations_are_absent():
    from swforge.server import mcp
    for name in ('sw_check_gb_conformity','sw_plan_process_rules','sw_apply_process_rules','sw_plan_annotation_rules','sw_apply_annotation_rules'):
        assert name not in mcp._gateway.registry
        assert mcp._gateway.invoke(name,{})['error']=='unregistered'


def test_private_cli_operations_are_absent():
    help_text=subprocess.check_output([sys.executable,'-X','utf8','-m','swforge.cli','--help'],text=True,encoding='utf-8')
    for name in ('gb-conformity','raster-review','process-plan','process-apply','annotation-plan','annotation-apply'):
        assert name not in help_text
