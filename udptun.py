#!/usr/bin/env python3
"""UDP Tunnel
    updated on: 03/24/2025
    github: https://github.com/BarkerProoks/udp-tunnel
    version: 1.0.0

Copyright 2025 Jon Parker Brooks

Permission is hereby granted, free of charge, to any person obtaining a copy of this 
software and associated documentation files (the “Software”), to deal in the Software 
without restriction, including without limitation the rights to use, copy, modify, 
merge, publish, distribute, sublicense, and/or sell copies of the Software, and to 
permit persons to whom the Software is furnished to do so, subject to the following
conditions:

The above copyright notice and this permission notice shall be included in all copies 
or substantial portions of the Software.

THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, 
INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A 
PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT 
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF 
CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE 
OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""


from asyncio import run, get_running_loop, DatagramTransport, DatagramProtocol
from asyncio import sleep as asleep
from argparse import ArgumentParser


def string_to_addr(address: str) -> tuple[str, int]:
    host, port = address.split(':')
    return host, int(port)


def addr_to_string(address: tuple[str, int]) -> str:
    return f"{address[0]}:{address[1]}"


def udp_connect(protocol_factory: DatagramProtocol, addr: tuple[str, int]) -> tuple[DatagramTransport, DatagramProtocol]:
    return get_running_loop().create_datagram_endpoint(protocol_factory, remote_addr=addr)


def udp_bind(protocol_factory: DatagramProtocol, addr: tuple[str, int]) -> tuple[DatagramTransport, DatagramProtocol]:
    return get_running_loop().create_datagram_endpoint(protocol_factory, local_addr=addr)


class Command:
    SYN:     bytes = b"\x16"
    ACK:     bytes = b"\x06"
    SYNACK:  bytes = b"\x22"
    CLOSED:  bytes = b"\x03"
    CONNECT: bytes = b"\x05"


class ProxyTunnelProtocol(DatagramProtocol):
    """
    This protocol is the binding between a the forwarded port, and the port on the local
    side which handled passing the data to the local service 
    """
    transport: DatagramTransport | None = None
    forward: DatagramTransport | None = None

    # for initial connection
    tunnel_addr: tuple[str, int] | None = None
    client_data: bytes | None = None

    # persistent connection
    client_addr: tuple[str, int] | None = None
    
    verbose: bool = False

    def __init__(self, forward: DatagramProtocol) -> None:
        self.client_addr = forward.new_client_addr
        self.client_data = forward.new_client_data
        self.forward = forward.transport

    def connection_made(self, transport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if self.tunnel_addr:
            if self.verbose:
                print(f"proxy tunnel recv: client <- tunnel <- service")
                print(data)
            self.forward.sendto(data, self.client_addr)
        else:
            if self.verbose:
                print(f"proxy tunnel recv: connected {addr_to_string(addr)}")
                print(self.client_data_data)
            # ignore the contents and send the initial data
            self.transport.sendto(self.client_data, addr)
            # transport the new client data through the tunnel as quickly as possible
            self.tunnel_addr = addr # after this just listen, the forwarder will handle the rest


class ProxyForwardProtocol(DatagramProtocol):
    """
    The protocol responsible for binding to the desired forwarded port and accepting
    datagrams from clients to be forwarded through the tunnel.
    """
    transport: DatagramTransport | None = None

    # first time connection information to pass on
    new_client_data: bytes = None
    new_client_addr: tuple[str, int] = None

    # Key = IP Address
    tunnels: dict[str, ProxyTunnelProtocol] = {}

    verbose: bool = False

    def connection_made(self, transport):
        if self.verbose:
            address = self.transport.get_extra_info("sockname")
            print(f"proxy tunnel: opened on {address}")
        self.transport = transport

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if addr not in self.tunnels:
            if self.verbose:
                print(f"proxy forward recv: must add new client {addr_to_string(addr)}")
            self.new_client_addr = addr
            self.new_client_data = data
            return

        tunnel = self.tunnels[addr]
        if tunnel.tunnel_addr:
            if self.verbose:
                print(f"proxy forward recv: client -> tunnel -> service")
                print(data)
            tunnel.transport.sendto(data, tunnel.tunnel_addr)


class ProxyRouterProtocol(DatagramProtocol):
    """
    This protocol is responsible for managing the local side and telling when there is 
    a new port to add to the tunnel connections.
    """
    transport: DatagramTransport | None = None

    local_router_addr: tuple[str, int] | None = None # linked address. keep this alive the whole time 
    status: bytes = Command.CLOSED

    verbose: bool = False

    def connection_made(self, transport):
        if self.verbose:
            print("proxy router: waiting for initial handshake...")
        self.transport = transport

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        # the only things we send the local router are commands
        if self.status == Command.CLOSED and data == Command.SYN:
            if self.verbose:
                print(f"proxy router recv: syn, starting handshake from {addr_to_string(addr)}")
            self.status = Command.ACK
            self.transport.sendto(Command.ACK, addr)
        elif self.status == Command.ACK and data == Command.SYNACK:
            if self.verbose:
                print(f"proxy router recv: ack, handshake complete from {addr_to_string(addr)}")
            self.status = Command.SYNACK
            self.transport.sendto(self.status, addr)
            self.local_router_addr = addr # SYNACK means we've completed handshake


async def run_proxy_loop(forward_addr: tuple[str, int], bind_addr: tuple[str, int], verbose: bool = False) -> None:
    print(f"proxy: running ingress tunnel [{addr_to_string(forward_addr)} => {addr_to_string(bind_addr)}]")
    
    # open the public proxied port and the router
    forward_transport, forward_protocol = await udp_bind(ProxyForwardProtocol, forward_addr)
    router_transport, router_protocol = await udp_bind(ProxyRouterProtocol, bind_addr)

    router_protocol.verbose = forward_protocol.verbose = verbose

    # need to keep track of all connections so we can sever them gracefully
    transports: list[DatagramTransport] = [forward_transport, router_transport]

    try:
        print("proxy: waiting for local tunnel to connect...")
        while not router_protocol.status == Command.SYNACK:
            await asleep(0.1) # wait until connected

        print("proxy: connected to local tunnel")
        while router_protocol.status == Command.SYNACK:
            if forward_protocol.new_client_addr:
                
                protocol_factory = lambda: ProxyTunnelProtocol(forward_protocol)
                tunnel_addr = (forward_addr[0], 0) # bind on any available port

                # open up proxy tunnel
                if verbose:
                    print("proxy: binding an open port for new tunnel")
                tunnel_transport, tunnel_protocol = await udp_bind(protocol_factory, tunnel_addr)
                tunnel_protocol.verbose = verbose

                forward_protocol.tunnels[forward_protocol.new_client_addr] = tunnel_protocol

                _, port = tunnel_transport.get_extra_info("sockname")
                tunnel_cmd = f"{port}".encode("utf-8")

                if verbose:
                    print(f"proxy: sending connect request for port {port}")
                router_transport.sendto(Command.CONNECT + tunnel_cmd, router_protocol.local_router_addr)

                forward_protocol.new_client_addr = None
                forward_protocol.new_client_data = None

                transports.append(tunnel_transport)
            # keep-alive
            router_transport.sendto(Command.SYNACK, router_protocol.local_router_addr)
            await asleep(0.1)
    except KeyboardInterrupt:
        raise KeyboardInterrupt
    finally:
        print("closing proxy connections")
        for transport in transports:
            if verbose:
                print(f" - closing {transport.get_protocol().__class__.__name__}")
            transport.close()


class LocalTunnelProtocol(DatagramProtocol):
    """
    This protocol acts as the local binding between the desired service and the 
    proxy. It will take the data sent from the client over the proxy and pass it to the
    local listening service.
    """
    transport: DatagramTransport | None = None
    forward: DatagramTransport | None= None

    verbose: bool = False

    def connection_made(self, transport) -> None:
        if self.verbose:
            print(f"local tunnel: connected to {addr_to_string(transport._address)}")
        self.transport = transport
        self.transport.sendto(Command.CONNECT) # confirm connection by sending addr to server

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if self.verbose:
            print("local tunnel recv: service <- tunnel <- client")
            print(data)
        self.forward.sendto(data) # forward it directly to the service


class LocalForwardProtocol(DatagramProtocol):
    """
    The protocol responsible for communicating with the desired service. Each forward
    protocol should have a sister tunnel protocol. The forward protocol sends data
    from the local service back through the tunnel.
    """
    transport: DatagramTransport | None = None
    tunnel: LocalTunnelProtocol | None = None
    verbose: bool = False

    def connection_made(self, transport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, _) -> None:
        if self.verbose:
            print("local forward recv: service -> tunnel -> client")
            print(data)
        self.tunnel.transport.sendto(data)


class LocalRouterProtocol(DatagramProtocol):
    """
    This protocol is responsible for taking commands from the proxy side and
    telling when there is a new port to add to the tunnel connections.
    """
    transport: DatagramTransport | None = None

    new_tunnel_port: int | None = None
    status: bytes = Command.CLOSED
    
    verbose: bool = False

    def connection_made(self, transport: DatagramTransport) -> None:
        if self.verbose:
            print(f'local router: sending initial handshake...')
        self.transport = transport
        self.transport.sendto(Command.SYN)

    def datagram_received(self, data: bytes, _) -> None:
        if len(data) == 1: # router base connection commands
            if self.status == Command.CLOSED and data == Command.ACK:
                if self.verbose:
                    print("local router recv: handshake complete")
                self.status = Command.SYNACK # we acknowledge and send
                self.transport.sendto(Command.SYNACK)
            if self.status == Command.SYNACK and data == Command.SYNACK:
                self.transport.sendto(self.status) # respond to keep-alive
        elif len(data) > 1: # tunnel connect is the only command longer than 1 byte
            if self.verbose:
                print("local router recv: incoming connection request")
            if data[0] == Command.CONNECT[0]:
                # if this is not a number we have a real issue >:(
                self.new_tunnel_port = int(data[1:])


async def run_local_loop(forward_addr: tuple[str, int], connect_addr: tuple[str, int], verbose: bool) -> None:
    print(f"local: running egress tunnel [{addr_to_string(forward_addr)} => {addr_to_string(connect_addr)}]")

    # connect to the routing service
    router_transport, router_protocol = await udp_connect(LocalRouterProtocol, connect_addr)
    router_protocol.verbose = verbose

    # need to keep track of all transports
    transports: list[DatagramTransport] = [router_transport]

    try:
        print("local: attempting handshake...")
        while not router_protocol.status == Command.SYNACK:
            if verbose:
                print("local: retrying handshake...")
            router_transport.sendto(Command.SYN)
            await asleep(1)

        print("local: connected to proxy")
        while router_protocol.status == Command.SYNACK: # while we're connected
            # this not being None indicates a new connection
            if router_protocol.new_tunnel_port is not None:
                if verbose:
                    print(f"local: connecting to new tunnel on port {router_protocol.new_tunnel_port}")
                tunnel_addr = (connect_addr[0], router_protocol.new_tunnel_port)

                # create the tunnel connection
                forward_transport, forward_protocol = await udp_connect(LocalForwardProtocol, forward_addr)
                tunnel_transport, tunnel_protocol = await udp_connect(LocalTunnelProtocol, tunnel_addr)

                forward_protocol.verbose = verbose
                tunnel_protocol.verbose = verbose

                # link the new tunnel / forwarder transports
                tunnel_protocol.forward = forward_transport
                forward_protocol.tunnel = tunnel_protocol

                transports.extend([tunnel_transport, forward_transport])
                router_protocol.new_tunnel_port = None
            # async needs a delay to process things
            await asleep(0.1)
    except KeyboardInterrupt:
        raise KeyboardInterrupt
    finally:
        print("closing local connections")
        for transport in transports:
            if verbose:
                print(f" - closing {transport.get_protocol().__class__.__name__}")
            transport.close()


async def main(args) -> None:
    forward_addr = string_to_addr(args.forward)
    match args.mode:
        case "local": 
            args.connect = args.connect if ':' in args.connect else f"{args.connect}:4300"
            await run_local_loop(forward_addr, string_to_addr(args.connect), args.verbose)
        case "proxy": await run_proxy_loop(forward_addr, string_to_addr(args.bind), args.verbose)


if __name__ == "__main__":
    parser = ArgumentParser()
    subparsers = parser.add_subparsers(dest="mode", required=True)

    proxy_subparser = subparsers.add_parser("proxy")
    proxy_subparser.add_argument("-f", "--forward", type=str, required=True,
                                 help="The address to expose to the internet.")
    proxy_subparser.add_argument("-b", "--bind", type=str, default="0.0.0.0:4300",
                                 help="The address on which to bind the connection router. (default: 0.0.0.0:4300)")
    proxy_subparser.add_argument("-v", "--verbose", action="store_true", 
                        help="Print detailed information including transmitted content")

    local_subparser = subparsers.add_parser("local")
    local_subparser.add_argument("-f", "--forward", type=str, required=True,
                                 help="The address to expose to the internet.")
    local_subparser.add_argument("-c", "--connect", type=str, required=True, 
                                 help="The address to connect to for routing connections.")
    local_subparser.add_argument("-v", "--verbose", action="store_true", 
                        help="Print detailed information including transmitted content")

    try:
        run(main(parser.parse_args()))
    except KeyboardInterrupt:
        print("ctrl+c detected, quitting")
