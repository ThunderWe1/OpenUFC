"""Termination policy shared by all application VISA connections."""

from pyvisa.constants import InterfaceType, ResourceAttribute


def configure_visa_termination(resource) -> None:
    info = resource.resource_info
    if info.interface_type in (InterfaceType.gpib, InterfaceType.gpib_vxi):
        raise ValueError("GPIB connections are not supported. Connect the instrument via USB or LAN.")
    resource.write_termination = "\n"
    resource.read_termination = "\n"
    if info.interface_type in (InterfaceType.usb, InterfaceType.tcpip) and info.resource_class == "INSTR":
        # USBTMC and LAN instrument protocols frame replies themselves. Keep
        # PyVISA's trailing newline handling without splitting binary payloads.
        resource.set_visa_attribute(ResourceAttribute.termchar_enabled, False)
