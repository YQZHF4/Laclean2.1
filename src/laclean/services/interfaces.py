"""Reserved hardware and planning boundaries.

The UI depends on these protocols instead of vendor SDKs. Concrete adapters will
be added when hardware communication is implemented.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CameraAdapter(Protocol):
    def connect(self) -> None: ...

    def disconnect(self) -> None: ...

    def capture(self) -> Any: ...


@runtime_checkable
class RobotAdapter(Protocol):
    def connect(self) -> None: ...

    def disconnect(self) -> None: ...

    def send_joint_positions(self, joints: list[float]) -> None: ...


@runtime_checkable
class GalvoAdapter(Protocol):
    def connect(self) -> None: ...

    def disconnect(self) -> None: ...


@runtime_checkable
class PathPlanningService(Protocol):
    def generate(self, parameters: dict[str, Any]) -> Any: ...


@runtime_checkable
class CollisionService(Protocol):
    def check(self, scene: Any, robot_state: Any) -> Any: ...
