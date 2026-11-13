"""Cross-callback cycles stop Dash scheduling updates across the whole app."""
from graphlib import TopologicalSorter

from tests.test_daily_report_page import application_namespace


def test_application_callbacks_have_no_cross_callback_dependency_cycles():
    namespace, _ = application_namespace()
    graph = {}
    for callback in namespace['app'].callback_map.values():
        outputs = callback['output']
        outputs = outputs if isinstance(outputs, list) else [outputs]
        inputs = {f"{item['id']}.{item['property']}" for item in callback['inputs']}
        # Dash supports circular synchronization inside one callback by
        # separating its overlapping input/output properties in its graph.
        circular = {f'{out.component_id}.{out.component_property}' for out in outputs} & inputs
        for output in outputs:
            target = f'{output.component_id}.{output.component_property}'
            if target in circular:
                target += '__output'
            graph.setdefault(target, set()).update(inputs)
    tuple(TopologicalSorter(graph).static_order())
