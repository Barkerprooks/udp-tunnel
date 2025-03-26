#!/usr/bin/python3

# created by: Jon Parker Brooks
# started on: --/--/---- 
# updated on: 03/24/2025
# github: BarkerProoks


# NOTE: I... hate... OOP... Why is the async API like this???


from asyncio import run, get_running_loop, DatagramTransport, DatagramProtocol
from asyncio import sleep as asleep
from argparse import ArgumentParser


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


"""
Proxy Tunnel / Internet Facing:
TODO: write a description about how all this works
"""


class ProxyTunnelProtocol(DatagramProtocol):
    """
    TODO: write description
    """

    transport: DatagramTransport | None = None
    forward: DatagramTransport | None = None

    local_tunnel_addr: tuple[str, int] | None = None
    src_addr: tuple[str, int] | None = None
    new_data: bytes | None = None

    def __init__(self, new_data: bytes, src_addr: tuple[str, int], forward: DatagramTransport) -> None:
        self.new_data = new_data
        self.src_addr = src_addr
        self.forward = forward

    def connection_made(self, transport) -> None:
        self.transport = transport


    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:

        if self.local_tunnel_addr:
            print(f"proxy tunnel recv: forwarding to {addr_to_string(self.src_addr)}")
            print(data)
            self.forward.sendto(data, self.src_addr)
        else: # this first one to get it goes thru, 
            print(f"proxy tunnel recv: connected {addr_to_string(addr)}")
            # ignore the contents and send the initial data
            self.transport.sendto(self.new_data, addr)
            # transport the new client data through the tunnel as quickly as possible
            self.local_tunnel_addr = addr # after this just listen, the forwarder will handle the rest

    def connection_lost(self, exc):
        print("proxy tunnel: lost connection")

class ProxyForwardProtocol(DatagramProtocol):
    """
    TODO: write description
    """
    transport: DatagramTransport | None = None

    new_tunnel_data: bytes = None
    new_tunnel_addr: tuple[str, int] = None

    # Key = IP Address
    tunnels: dict[str, ProxyTunnelProtocol] = {}

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if addr not in self.tunnels:
            print("proxy forward recv: must add new client")
            self.new_tunnel_addr = addr
            self.new_tunnel_data = data
            return

        tunnel = self.tunnels[addr]
        if tunnel.local_tunnel_addr:
            print(f"client {addr_to_string(addr)} sending data though {tunnel.local_tunnel_addr}")
            print(data)
            tunnel.transport.sendto(data, tunnel.local_tunnel_addr)


    def connection_lost(self, exc):
        print("proxy forward: lost connection")


class ProxyRouterProtocol(DatagramProtocol):
    """
    TODO: write description
    """
    transport: DatagramTransport | None = None

    local_router_addr: tuple[str, int] = [] # linked address. keep this alive the whole time 
    status: bytes = Command.CLOSED

    def connection_made(self, transport):
        print("proxy router: waiting for initial handshake...")
        self.transport = transport

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        # the only things we send the local router are commands
        if self.status == Command.CLOSED and data == Command.SYN:
            print(f"proxy router recv: syn, starting handshake from {addr_to_string(addr)}")
            self.status = Command.ACK
            self.transport.sendto(Command.ACK, addr)
        elif self.status == Command.ACK and data == Command.SYNACK:
            print(f"proxy router recv: ack, handshake complete from {addr_to_string(addr)}")
            self.status = Command.SYNACK
            self.transport.sendto(self.status, addr)
            self.local_router_addr = addr # SYNACK means we've completed handshake


async def run_proxy_loop(forward_addr: tuple[str, int], bind_addr: tuple[str, int]) -> None:
    print(f"proxy: running ingress tunnel [{addr_to_string(forward_addr)} => {addr_to_string(bind_addr)}]")
    
    # open the public proxied port and the router
    forward_transport, forward_protocol = await udp_bind(ProxyForwardProtocol, forward_addr)
    router_transport, router_protocol = await udp_bind(ProxyRouterProtocol, bind_addr)

    # need to keep track of all connections so we can sever them gracefully
    transports: list[DatagramTransport] = [forward_transport, router_transport]

    slot = 0 # use rolling number to assign ports

    try:
        while True:
            if forward_protocol.new_tunnel_addr:
                port = slot + 45535
                slot = (slot + 1) % 20000
            
                tunnel_addr = (forward_addr[0], port)
                tunnel_cmd = f"{port}".encode("utf-8")

                print(f"proxy: opening tunnel port {port}")

                protocol_factory = lambda: ProxyTunnelProtocol(
                    forward_protocol.new_tunnel_data,
                    forward_protocol.new_tunnel_addr,
                    forward_transport
                )

                tunnel_transport, tunnel_protocol = await udp_bind(protocol_factory, tunnel_addr)
                forward_protocol.tunnels[tunnel_addr[0]] = tunnel_protocol

                print("proxy: sending connect request")
                router_transport.sendto(Command.CONNECT + tunnel_cmd, router_protocol.local_router_addr)

                forward_protocol.new_tunnel_addr = None
                forward_protocol.new_tunnel_data = None

                transports.append(tunnel_transport)
            # keep-alive
            if router_protocol.status == Command.SYNACK:
                router_transport.sendto(Command.SYNACK, router_protocol.local_router_addr)

            await asleep(0.1)
    except KeyboardInterrupt:
        raise KeyboardInterrupt
    finally:
        print("closing proxy connections")
        for transport in transports:
            print(f"closing {transport.get_protocol().__class__.__name__}")
            transport.close()

"""
Local Tunnel / Port Forwarding:
TODO: write a description about how all this works
"""


class LocalTunnelProtocol(DatagramProtocol):
    """
    This protocol acts as the local binding between the desired service and the 
    proxy.
    """
    transport: DatagramTransport = None
    forward: DatagramTransport = None

    def connection_made(self, transport) -> None:
        print(f"local tunnel: connected to {transport._address}")
        self.transport = transport
        self.transport.sendto(Command.CONNECT) # confirm connection by sending addr to server

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if self.forward.proxy_tunnel_addr:
            print("local tunnel: data coming from client incoming to service")
            print(data)
            self.forward.sendto(data, self.forward.proxy_tunnel_addr) # forward it di rectly to the service
        else:
            print("local tunnel: forwarder not connected for some reason")

class LocalForwardProtocol(DatagramProtocol):
    """
    The protocol responsible for communicating with the desired service. Each forward
    protocol should have a sister tunnel protocol. The forward protocol sends data
    from the local service back through the tunnel
    """
    transport: DatagramTransport | None = None
    tunnel: DatagramTransport | None = None

    proxy_tunnel_addr: tuple[str, int] | None = None

    def connection_made(self, transport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        print("local forward: data coming from service outgoing to client")
        print(data)
        self.tunnel.sendto(data)
        self.proxy_tunnel_addr = addr


class LocalRouterProtocol(DatagramProtocol):
    """
    This protocol is responsible for taking commands from the proxy side and
    telling when there is a new port to add to the tunnel connections
    """
    transport: DatagramTransport | None = None

    new_tunnel_port: int | None = None
    status: bytes = Command.CLOSED

    def __retry_handshake(self) -> None:
        self.transport.sendto(Command.SYN)

    def connection_made(self, transport: DatagramTransport) -> None:
        print(f'local router: sending initial handshake...')
        self.transport = transport
        self.transport.sendto(Command.SYN)

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if len(data) == 1: # router base connection commands
            if self.status == Command.CLOSED and data == Command.ACK:
                print("local router: handshake complete")
                self.status = Command.SYNACK # we acknowledge and send
                self.transport.sendto(Command.SYNACK)
            if self.status == Command.SYNACK and data == Command.SYNACK:
                self.transport.sendto(self.status) # respond to keep-alive
        elif len(data) > 1: # tunnel connect is the only command longer than 1 byte
            print("local router recv: incoming connection request")
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


async def run_local_loop(forward_addr: tuple[str, int], connect_addr: tuple[str, int]) -> None:
    print(f"local: running egress tunnel [{addr_to_string(forward_addr)} => {addr_to_string(connect_addr)}]")

    # connect to the routing service
    router_transport, router_protocol = await udp_connect(LocalRouterProtocol, connect_addr)
    
    # need to keep track of all transports
    transports: list[DatagramTransport] = [router_transport]

    try:
        while True:
            # this not being None indicates a new connection
            if router_protocol.new_tunnel_port is not None:
                print("local: adding new tunnel")
                tunnel_addr = (connect_addr[0], router_protocol.new_tunnel_port)

                # create the pair of connections
                tunnel_transport, tunnel_protocol = await udp_connect(LocalTunnelProtocol, tunnel_addr)
                forward_transport, forward_protocol = await udp_connect(LocalForwardProtocol, forward_addr)
                
                # link the new tunnel / forwarder transports
                tunnel_protocol.forward = forward_transport
                forward_protocol.tunnel = tunnel_transport

                transports.extend([forward_transport, tunnel_transport])
                router_protocol.new_tunnel_port = None
            # async needs a delay to process things
            await asleep(0.1)
    except KeyboardInterrupt:
        raise KeyboardInterrupt
    finally:
        print("closing local connections")
        for transport in transports:
            print(f"closing {transport.get_protocol().__class__.__name__}")
            transport.close()


"""
Async UDP - Tunnel / Port Forwarder
    TODO: write description here
"""


async def main(args) -> None:
    forward_addr = string_to_addr(args.forward)
    match args.mode:
        case "local": await run_local_loop(forward_addr, string_to_addr(args.connect))
        case "proxy": await run_proxy_loop(forward_addr, string_to_addr(args.bind))


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