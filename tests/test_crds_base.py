import pytest
from unittest.mock import MagicMock, patch
from devservers.crds.base import BaseCustomResource, ObjectMeta, _is_status_subset
import time

# A minimal concrete implementation of the abstract base class for testing
class MyCustomResource(BaseCustomResource):
    group = "test.group"
    version = "v1"
    plural = "mycustomresources"
    namespaced = True

    def __init__(self, metadata, spec, status=None, api=None):
        super().__init__(api)
        self.metadata = metadata
        self.spec = spec
        self.status = status or {}

@pytest.fixture
def custom_resource(mock_k8s_api):
    """Fixture to create a MyCustomResource instance with a mocked API."""
    metadata = ObjectMeta(name="test-resource", namespace="default")
    spec = {"key": "value"}
    return MyCustomResource(metadata, spec, api=mock_k8s_api)

def test_wait_for_status_already_correct(custom_resource):
    """Test that wait_for_status returns immediately if status is already correct."""
    custom_resource.status = {"state": "Ready", "extra": "field"}

    # Mock the refresh method to update the status
    def refresh_side_effect():
        custom_resource.status = {"state": "Ready", "extra": "field"}

    custom_resource.refresh = MagicMock(side_effect=refresh_side_effect)

    # The call should not block or raise an exception
    for _ in custom_resource.wait_for_status(status={"state": "Ready"}, timeout=1):
        pass # Consume generator

    custom_resource.refresh.assert_called_once()


def test_wait_for_status_succeeds_after_event(custom_resource):
    """Test that wait_for_status succeeds after receiving a watch event."""
    custom_resource.status = {"state": "Pending"}
    desired_status = {"state": "Ready"}

    # When refresh is called, simulate the status being updated on the object,
    # but only after the first call.
    def refresh_side_effect():
        # The first call to refresh() happens before the watch.
        # The second call happens after the watch event is received.
        if custom_resource.refresh.call_count > 1:
            custom_resource.status = {"state": "Ready", "refreshed": True}
    custom_resource.refresh = MagicMock(side_effect=refresh_side_effect)


    # Mock the watch to return an event with the desired status
    mock_watch_event = {
        "type": "MODIFIED",
        "object": {
            "metadata": {"name": "test-resource"},
            "spec": {},
            "status": {"state": "Ready", "source": "event"},
        },
    }

    with patch.object(custom_resource, 'watch', return_value=[mock_watch_event]) as mock_watch:
        # Consume the generator to run the function
        events = list(custom_resource.wait_for_status(status=desired_status, timeout=10))

        assert len(events) == 1
        assert events[0] == mock_watch_event

    # The first refresh call happens at the beginning of the function, and the second
    # happens after the event with the desired status is received.
    assert custom_resource.refresh.call_count == 2
    mock_watch.assert_called_once()


def test_wait_for_status_timeout(custom_resource):
    """Test that wait_for_status raises TimeoutError on timeout."""
    custom_resource.status = {"state": "Pending"}

    # Mock refresh to do nothing
    custom_resource.refresh = MagicMock()

    # Mock the watch to return no events, simulating a timeout
    with patch.object(custom_resource, 'watch', return_value=[]) as mock_watch:
        with pytest.raises(TimeoutError):
            # Use a very small timeout to ensure it triggers
            list(custom_resource.wait_for_status(status={"state": "Ready"}, timeout=0.1))

    # In a timeout scenario, the watch might not be called if the initial checks
    # take longer than the timeout. So we assert it was called at most once.
    assert mock_watch.call_count <= 1


def test_wait_for_status_yields_events(custom_resource):
    """Test that wait_for_status correctly yields events."""
    custom_resource.status = {"state": "Pending"}
    desired_status = {"state": "Ready"}

    def refresh_side_effect():
        # Simulate the final status update when refresh is called
        if custom_resource.refresh.call_count > 1:
             custom_resource.status = {"state": "Ready", "final": True}
    custom_resource.refresh = MagicMock(side_effect=refresh_side_effect)

    events_to_yield = [
        {"type": "MODIFIED", "object": {"status": {"state": "Processing"}}},
        {"type": "MODIFIED", "object": {"status": {"state": "Ready", "extra": "data"}}},
    ]

    with patch.object(custom_resource, 'watch', return_value=events_to_yield):
        received_events = []
        for event in custom_resource.wait_for_status(status=desired_status, timeout=10): # Increased timeout
            received_events.append(event)

        assert received_events == events_to_yield


def test_wait_for_status_blocking_usage(custom_resource):
    """Test that the generator can be consumed to block execution."""
    custom_resource.status = {"state": "Pending"}
    desired_status = {"state": "Ready"}

    def refresh_side_effect():
        custom_resource.status = {"state": "Ready", "refreshed": True}
    custom_resource.refresh = MagicMock(side_effect=refresh_side_effect)

    mock_watch_event = {
        "type": "MODIFIED",
        "object": {"status": {"state": "Ready", "from_event": True}},
    }

    with patch.object(custom_resource, 'watch', return_value=[mock_watch_event]):
        # Block by consuming the generator
        for _ in custom_resource.wait_for_status(status=desired_status, timeout=10): # Increased timeout
            pass

        # If we get here without a timeout, the test has passed.
        # The refresh mock will have been called, so the status should be updated.
        assert _is_status_subset(desired_status, custom_resource.status)


def endless_watch_generator(*args, **kwargs):
    """
    A generator that simulates a watch that respects timeout_seconds.
    It never provides the desired status, so it will force the timeout logic to be exercised.
    """
    timeout = kwargs.get("timeout_seconds", 5)
    start_time = time.time()
    while time.time() - start_time < timeout:
        yield {
            "type": "MODIFIED",
            "object": {
                "metadata": {"name": "test-server"},
                "status": {"state": "SomethingElse"}
            }
        }
        time.sleep(0.1)  # prevent cpu spinning, but stay within the timeout


@pytest.mark.timeout(10)
def test_wait_for_status_potential_hang(mock_k8s_api):
    """
    This test verifies that wait_for_status will time out if the watch stream never provides the desired status
    and never terminates on its own.
    """
    metadata = ObjectMeta(name="test-server", namespace="default")
    spec = {}
    status = {"state": "Starting"}

    # This mock is for the refresh() call inside wait_for_status
    mock_k8s_api.get_namespaced_custom_object.return_value = {
        "metadata": {"name": "test-server", "namespace": "default"},
        "spec": spec,
        "status": status,
    }

    resource = MyCustomResource(metadata=metadata, spec=spec, status=status, api=mock_k8s_api)

    # Replace the watch method with our endless generator
    resource.watch = endless_watch_generator

    with pytest.raises(TimeoutError):
        # We expect this to time out based on the logic inside wait_for_status, not pytest.mark.timeout
        # The pytest timeout is a safety net.
        for _ in resource.wait_for_status({"state": "Ready"}, timeout=5):
            pass


def test_wait_for_status_reaches_desired_state_from_readme(mock_k8s_api):
    """
    This test verifies that wait_for_status correctly completes when the desired status is reached,
    simulating the example in the README.
    """
    metadata = ObjectMeta(name="test-server", namespace="default")
    spec = {}
    initial_status = {"phase": "Starting"}
    desired_status = {"phase": "Running"}

    # Simulate a sequence of events from the watch
    events = [
        {
            "type": "MODIFIED",
            "object": {
                "metadata": {"name": "test-server", "namespace": "default"},
                "spec": spec,
                "status": {"phase": "Provisioning"}
            }
        },
        {
            "type": "MODIFIED",
            "object": {
                "metadata": {"name": "test-server", "namespace": "default"},
                "spec": spec,
                "status": {"phase": "Running"}
            }
        }
    ]

    # The mock for get_namespaced_custom_object needs to return different values
    # on subsequent calls to simulate the status update during refresh().
    mock_k8s_api.get_namespaced_custom_object.side_effect = [
        # First call at the start of wait_for_status
        {
            "metadata": {"name": "test-server", "namespace": "default"},
            "spec": spec,
            "status": initial_status,
        },
        # Second call after the "Running" event is received
        events[1]["object"],
        # Any subsequent calls
        events[1]["object"],
    ]

    def mock_watch_generator(*args, **kwargs):
        for event in events:
            yield event

    resource = MyCustomResource(metadata=metadata, spec=spec, status=initial_status, api=mock_k8s_api)
    resource.watch = mock_watch_generator

    # Iterate through the generator as shown in the README example
    try:
        event_count = 0
        for event in resource.wait_for_status(status=desired_status, timeout=10):
            event_count += 1
            print(f"Received event: {event['type']}, status: {event['object'].get('status')}")

    except TimeoutError:
        pytest.fail("wait_for_status timed out unexpectedly")

    # Assert that we received the events and the final status is correct
    assert event_count == 2
    assert _is_status_subset(desired_status, resource.status)
