import itertools
import unittest
from pathlib import Path

from harness.adapter_conformance import (
    AdapterConformanceFixture,
    RuntimeAdapterConformanceMixin,
)
from harness.reference_adapter import (
    PartialToolFailure,
    ReferenceRuntimeAdapter,
)
from harness.runtime import SideEffect


class ReferenceAdapterConformanceTests(RuntimeAdapterConformanceMixin, unittest.TestCase):
    def make_adapter_fixture(self) -> AdapterConformanceFixture:
        identifiers = itertools.count(1)
        effect = SideEffect(
            kind="file-write",
            target="output/partial.txt",
            description="Created the file before the simulated failure.",
            reversible=True,
        )

        def fail(_arguments: dict[str, object]) -> None:
            raise RuntimeError("simulated tool failure")

        def partial(_arguments: dict[str, object]) -> None:
            raise PartialToolFailure(
                "simulated partial failure",
                (effect,),
                {"bytes_written": 7},
            )

        adapter = ReferenceRuntimeAdapter(
            actor="host:conformance",
            handlers={
                "conformance.success": lambda _arguments: {"accepted": True},
                "conformance.failure": fail,
                "conformance.partial": partial,
                "conformance.timeout": lambda _arguments: {"unexpected": True},
            },
            id_factory=lambda: f"conformance-{next(identifiers)}",
            clock=lambda: "2026-08-08T12:00:00Z",
        )
        return AdapterConformanceFixture(
            adapter=adapter,
            schema_root=Path(__file__).resolve().parent.parent,
            actor="host:conformance",
            success_tool_id="conformance.success",
            success_arguments={"nested": {"value": 1}},
            success_output={"accepted": True},
            failure_tool_id="conformance.failure",
            failure_error="simulated tool failure",
            partial_tool_id="conformance.partial",
            partial_output={"bytes_written": 7},
            partial_effects=(effect,),
            timeout_tool_id="conformance.timeout",
        )


if __name__ == "__main__":
    unittest.main()
