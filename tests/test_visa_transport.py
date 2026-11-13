"""Verify the termination policy through each application connection path."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pyvisa.constants import InterfaceType, ResourceAttribute

from laser_platform import devices
from laser_platform.dmm.instrument.base import InstrumentError
from laser_platform.dmm.instrument.visa_client import VisaInstrumentClient
from laser_platform.ufc.instrument import CounterConfig, Keysight53230A


@pytest.mark.parametrize("interface,resource_class,disabled", [
    (InterfaceType.usb, "INSTR", True),
    (InterfaceType.tcpip, "INSTR", True),
    (InterfaceType.tcpip, "SOCKET", False),
    (InterfaceType.usb, "RAW", False),
    (InterfaceType.asrl, "INSTR", False),
])
@pytest.mark.parametrize("path", ["counter", "dmm", "identity"])
def test_connection_termination_policy(monkeypatch, interface, resource_class, disabled, path):
    resource = Mock(resource_info=SimpleNamespace(interface_type=interface, resource_class=resource_class))
    resource.query.return_value = "Keysight,34461A,TEST,1"
    manager = Mock(open_resource=Mock(return_value=resource))
    monkeypatch.setattr(devices.pyvisa, "ResourceManager", lambda: manager)
    address = "USB0::0x0957::0x1907::TEST::INSTR"
    if path == "identity":
        devices._visa_identity(manager, address)
    else:
        client = Keysight53230A() if path == "counter" else VisaInstrumentClient()
        try:
            if path == "counter":
                client.configure(CounterConfig(address))
                client.connect()
            else:
                client.connect(address)
        finally:
            client.close()
    assert resource.read_termination == resource.write_termination == "\n"
    if disabled:
        resource.set_visa_attribute.assert_called_once_with(ResourceAttribute.termchar_enabled, False)
    else:
        resource.set_visa_attribute.assert_not_called()


@pytest.mark.parametrize("interface", [InterfaceType.gpib, InterfaceType.gpib_vxi])
@pytest.mark.parametrize("path", ["counter", "dmm", "identity"])
def test_gpib_rejected_and_closed_even_through_visa_alias(monkeypatch, interface, path):
    resource = Mock(resource_info=SimpleNamespace(interface_type=interface, resource_class="INSTR"))
    manager = Mock(open_resource=Mock(return_value=resource))
    monkeypatch.setattr(devices.pyvisa, "ResourceManager", lambda: manager)
    with pytest.raises((ValueError, InstrumentError), match="GPIB connections are not supported"):
        if path == "identity":
            devices._visa_identity(manager, "BenchMeter")
        elif path == "counter":
            client = Keysight53230A()
            client.configure(CounterConfig("BenchMeter"))
            client.connect()
        else:
            client = VisaInstrumentClient()
            client.connect("BenchMeter")
    resource.query.assert_not_called()
    resource.write.assert_not_called()
    resource.close.assert_called_once()
    if path == "counter":
        assert client._inst is None
    elif path == "dmm":
        assert client.identity is None and client.resource_name is None


@pytest.mark.parametrize("rate,gate", [(5000, 0.0002), (10000, 0.0001), (50000, 0.00002)])
def test_high_rate_configures_gate_and_one_second_batch(rate, gate):
    client = Keysight53230A()
    client._inst = Mock()
    config = CounterConfig("USB::TEST", sample_rate_hz=rate)
    client.configure(config)
    assert config.chunk_size == rate
    assert config.gate_time_s == pytest.approx(gate)
    client._inst.write.assert_any_call(f"SENS:FREQ:GATE:TIME {gate:.12g}")
    client._inst.write.assert_any_call("SAMP:COUN 1000000")
