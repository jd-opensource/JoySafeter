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

    file_descriptor = descriptor_pb2.FileDescriptorProto.FromString(joysafeter_pb2.DESCRIPTOR.serialized_pb)
    message_descriptor = next(message for message in file_descriptor.message_type if message.name == "MemoryStoreMount")
    assert list(message_descriptor.reserved_name) == ["store_id"]
    assert [(item.start, item.end) for item in message_descriptor.reserved_range] == [(1, 2)]


def test_setup_sandbox_does_not_duplicate_task_file_delivery() -> None:
    fields = joysafeter_pb2.SetupSandbox.DESCRIPTOR.fields_by_name
    assert "files" not in fields
    assert "file_refs" not in fields

    file_descriptor = descriptor_pb2.FileDescriptorProto.FromString(joysafeter_pb2.DESCRIPTOR.serialized_pb)
    message_descriptor = next(message for message in file_descriptor.message_type if message.name == "SetupSandbox")
    assert {"files", "file_refs"} <= set(message_descriptor.reserved_name)
    assert (13, 15) in [(item.start, item.end) for item in message_descriptor.reserved_range]


def test_runner_protocol_does_not_expose_generic_secret_maps() -> None:
    file_descriptor = descriptor_pb2.FileDescriptorProto.FromString(joysafeter_pb2.DESCRIPTOR.serialized_pb)
    descriptors = {message.name: message for message in file_descriptor.message_type}

    assert "secrets" not in joysafeter_pb2.SetupSandbox.DESCRIPTOR.fields_by_name
    assert "secrets" in descriptors["SetupSandbox"].reserved_name
    assert (7, 8) in [(item.start, item.end) for item in descriptors["SetupSandbox"].reserved_range]

    assert "secrets" not in joysafeter_pb2.StartTask.DESCRIPTOR.fields_by_name
    assert "secrets" in descriptors["StartTask"].reserved_name
    assert (10, 11) in [(item.start, item.end) for item in descriptors["StartTask"].reserved_range]
