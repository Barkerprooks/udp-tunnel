#!/usr/bin/python3

# created by: Jon Parker Brooks
# started on: --/--/---- 
# updated on: 03/24/2025
# github: BarkerProoks

# I hate OOP... Why is the async API like this???

from asyncio import run, get_running_loop, DatagramTransport, DatagramProtocol
from asyncio import sleep as asleep
from argparse import ArgumentParser
from time import sleep


def string_to_addr(address: str) -> tuple[str, int]:
    host, port = address.split(':')
    return host, int(port)


def addr_to_string(address: tuple[str, int]) -> str:
    return f"{address[0]}:{address[1]}"


async def udp_connect(protocol_factory: DatagramProtocol, addr: tuple[str, int]) -> tuple[DatagramTransport, DatagramProtocol]:
    return await get_running_loop().create_datagram_endpoint(protocol_factory, remote_addr=addr)


async def udp_bind(protocol_factory: DatagramProtocol, addr: tuple[str, int]) -> tuple[DatagramTransport, DatagramProtocol]:
    return await get_running_loop().create_datagram_endpoint(protocol_factory, local_addr=addr, reuse_port=True)


class Command:
    SYN:     bytes = b"\x16"
    ACK:     bytes = b"\x06"
    SYNACK:  bytes = b"\x22"
    CLOSED:  bytes = b"\x03"
    CONNECT: bytes = b"\x05"
    QUIT:    bytes = b"\x04"


class ProxyTunnelProtocol(DatagramProtocol):
    transport: DatagramTransport
    forward: DatagramTransport

    local_tunnel_addr: tuple[str, int] | None = None
    src_addr: tuple[str, int] | None = None
    new_data: bytes | None = None

    def __init__(self, new_data: bytes, src_addr: tuple[str, int], forward: DatagramTransport) -> None:
        self.new_data = new_data
        self.src_addr = src_addr
        self.forward = forward

    def connection_made(self, transport) -> None:
        print("proxy tunnel: opened")
        self.transport = transport

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        print("proxy tunnel: yo nice", data)
        if self.local_tunnel_addr:
            self.forward.sendto(data, self.src_addr)
        else: # this first one to get it goes thru, 
            # ignore the contents and send the initial data
            self.local_tunnel_addr = addr
            self.transport.sendto(self.new_data, addr)


class ProxyForwardProtocol(DatagramProtocol):
    transport: DatagramTransport

    new_tunnel_data: bytes = None
    new_tunnel_addr: tuple[str, int] = None
    tunnels: dict[tuple[str, int], ProxyTunnelProtocol] = {}

    def connection_made(self, transport):
        print("proxy forwarder open")
        self.transport = transport

    def datagram_received(self, data, addr):
        print("received data from internet client")
        if addr not in self.tunnels:
            print("must add new client")
            self.new_tunnel_addr = addr
            self.new_tunnel_data = data
            return

        tunnel = self.tunnels[addr]
        if tunnel.local_tunnel_addr:
            self.tunnel.transport.sendto(data, tunnel.local_tunnel_addr)


class ProxyRouterProtocol(DatagramProtocol):
    transport: DatagramTransport

    local_router_addr: tuple[str, int] = [] # linked address. keep this alive the whole time 
    status: bytes = Command.CLOSED

    def connection_made(self, transport):
        print('proxy router: binding to routing service, waiting for initial handshake')
        self.transport = transport

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        # the only things we send the local router are commands
        if self.status == Command.CLOSED and data == Command.SYN:
            print("RECV: syn, starting handshake")
            self.status = Command.ACK
            self.transport.sendto(Command.ACK, addr)
        elif self.status == Command.ACK and data == Command.SYNACK:
            print("RECV: ack, handshake complete")
            self.status = Command.SYNACK
            self.transport.sendto(self.status, addr)
            self.local_router_addr = addr # SYNACK means we've completed handshake


async def main_proxy_loop(forward_addr: tuple[str, int], bind_addr: tuple[str, int]) -> None:
    """
    Main entry for the proxy side, binds to the service facing the internet.
    """

    router_transport, router_protocol = await udp_bind(ProxyRouterProtocol, bind_addr)
    forward_transport, forward_protocol = await udp_bind(ProxyForwardProtocol, forward_addr)
    
    tunnel_transports = []

    slot = 0

    try:
        print("started proxy")
        while True:
            if forward_protocol.new_tunnel_addr:
                slot = (slot + 1) % 20000
                port = slot + 45535
            
                tunnel_addr = (forward_addr[0], port)
                tunnel_cmd = f"{port}".encode("utf-8")

                print(f"opening tunnel port {port}")
                protocol_factory = lambda: ProxyTunnelProtocol(forward_protocol, forward_protocol.new_tunnel_data)
                tunnel_transport, tunnel_protocol = await udp_bind(protocol_factory, tunnel_addr)
                forward_protocol.tunnels[tunnel_addr] = tunnel_protocol

                print("sending connect request")
                router_transport.sendto(Command.CONNECT + tunnel_cmd, router_protocol.local_router_addr)

                forward_protocol.new_tunnel_addr = None
                forward_protocol.new_tunnel_data = None

                tunnel_transports.append(tunnel_transport)

            # keep-alive
            if router_protocol.status == Command.SYNACK:
                router_transport.sendto(Command.SYNACK, router_protocol.local_router_addr)

            await asleep(0.1)
    except KeyboardInterrupt:
        raise KeyboardInterrupt
    finally:
        print("closing proxy connections")
        for tunnel_transport in tunnel_transports:
            tunnel_transport.close()
        forward_transport.close()
        router_transport.close()


class LocalTunnelProtocol(DatagramProtocol):
    transport: DatagramTransport = None
    forward: DatagramTransport = None

    def connection_made(self, transport) -> None:
        print(f"local tunnel: connected to {transport._address}")
        self.transport = transport
        self.transport.sendto(Command.CONNECT) # confirm connection by sending addr to server

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        print("local tunnel: data coming from client incoming to service")
        self.forward.sendto(data) # forward it directly to the service


class LocalForwardProtocol(DatagramProtocol):
    """
    The protocol responsible for communicating with the desired service. Each forward
    protocol should have a sister tunnel protocol. The forward protocol sends data
    from the local service back through the tunnel
    """
    transport: DatagramTransport = None
    tunnel: DatagramTransport = None

    def connection_made(self, transport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        print("local forward: data coming from service outgoing to client")
        self.tunnel.sendto(data)


class LocalRouterProtocol(DatagramProtocol):
    """
    This protocol is responsible for taking commands from the proxy side and
    telling when there is a new port to add to the tunnel connections
    """
    transport: DatagramTransport    

    new_tunnel_port: int | None = None
    status: bytes = Command.CLOSED

    def __retry_handshake(self) -> None:
        print("retrying handshake...")
        self.transport.sendto(Command.SYN)
        sleep(2)

    def connection_made(self, transport: DatagramTransport) -> None:
        print('local router: connecting to routing service, sending initial handshake')
        self.transport = transport
        self.transport.sendto(Command.SYN)

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if len(data) == 1: # router base connection commands
            if self.status == Command.CLOSED and data == Command.ACK:
                print("RECV: ack, activated")
                self.status = Command.SYNACK # we acknowledge and send
                self.transport.sendto(Command.SYNACK)
            if self.status == Command.SYNACK and data == Command.SYNACK:
                self.transport.sendto(self.status) # respond to keep-alive
        else: # tunnel connect is the only command longer than 1 byte
            print("incoming connection request")
            if data[0] == Command.CONNECT[0]:
                # if this is not a number we have a real issue >:(
                self.new_tunnel_port = int(data[1:])

    def connection_lost(self, exc):
        if self.status != Command.SYNACK:
            self.status = Command.CLOSED
            self.__retry_handshake()

    def error_received(self, exc):
        if self.status != Command.SYNACK:
            self.status = Command.CLOSED
            self.__retry_handshake()


async def main_local_loop(forward_addr: tuple[str, int], connect_addr: tuple[str, int]) -> None:
    """
    Main entry for the local side, connects to the service from behind the proxy.
    """

    router_transport, router_protocol = await udp_connect(LocalRouterProtocol, connect_addr)
    forward_transports = []
    tunnel_transports = []

    try:
        print("running main loop")
        while True:
            if router_protocol.new_tunnel_port:
                print("adding new tunnel")
                tunnel_addr = (connect_addr[0], router_protocol.new_tunnel_port)

                tunnel_transport, tunnel_protocol = await udp_connect(LocalTunnelProtocol, tunnel_addr)
                forward_transport, forward_protocol = await udp_connect(LocalForwardProtocol, forward_addr)
                
                tunnel_protocol.forward = forward_transport
                forward_protocol.tunnel = tunnel_transport

                forward_transports.append(forward_transport)
                tunnel_transports.append(tunnel_transport)

                router_protocol.new_tunnel_port = None
            await asleep(0.1)
    except KeyboardInterrupt:
        raise KeyboardInterrupt
    finally:
        print("closing local connections")
        for forward_transport in forward_transports:
            forward_transport.close()
        for tunnel_transport in tunnel_transports:
            tunnel_transport.close()
        router_transport.close()


async def main(args) -> None:
    forward_addr = string_to_addr(args.forward)
    match args.mode:
        case "local":  await main_local_loop(forward_addr, string_to_addr(args.connect))
        case "proxy": await main_proxy_loop(forward_addr, string_to_addr(args.bind))


if __name__ == "__main__":
    parser = ArgumentParser()
    subparsers = parser.add_subparsers(dest="mode", required=True)

    proxy_subparser = subparsers.add_parser("proxy")
    proxy_subparser.add_argument("-f", "--forward", type=str, required=True,
                                 help="The address to expose to the internet.")
    proxy_subparser.add_argument("-b", "--bind", type=str, default="127.0.0.1:4300",
                                 help="The address on which to bind the connection router.")

    local_subparser = subparsers.add_parser("local")
    local_subparser.add_argument("-f", "--forward", type=str, required=True,
                                 help="The address to expose to the internet.")
    local_subparser.add_argument("-c", "--connect", type=str, required=True, 
                                 help="The address to connect to for routing connections.")

    try:
        run(main(parser.parse_args()))
    except KeyboardInterrupt:
        print("ctrl+c detected, quitting")