import pytest
from google.protobuf import descriptor_pb2

from app.joysafeter_shared.orchestrator_bridge.proto import joysafeter_pb2


pytestmark = pytest.mark.no_db


def test_harness_session_fields_keep_wire_numbers() -> None:
    expected = {
        joysafeter_pb2.RunnerIdle: 3,
        joysafeter_pb2.RunnerHarnessResult: 4,
        joysafeter_pb2.RunnerHeartbeat: 4,
        joysafeter_pb2.StartTask: 5,
    }

    for message_type, field_number in expected.items():
        fields = message_type.DESCRIPTOR.fields_by_name
        assert fields["harness_session_id"].number == field_number
        assert "session_id" not in fields


def test_task_notification_names_external_subagent_identity() -> None:
    fields = joysafeter_pb2.TaskNotificationEvent.DESCRIPTOR.fields_by_name

    assert fields["subagent_task_id"].number == 2
    assert "task_id" not in fields


def test_memory_store_mount_does_not_transport_unused_entity_identity() -> None:
    assert "store_id" not in joysafeter_pb2.MemoryStoreMount.DESCRIPTOR.fields_by_name

    file_descriptor = descriptor_pb2.FileDescriptorProto.FromString(
        joysafeter_pb2.DESCRIPTOR.serialized_pb
    )
    message_descriptor = next(
        message for message in file_descriptor.message_type if message.name == "MemoryStoreMount"
    )
    assert list(message_descriptor.reserved_name) == ["store_id"]
    assert [(item.start, item.end) for item in message_descriptor.reserved_range] == [(1, 2)]
