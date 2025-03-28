#!/usr/bin/env python3

from argparse import ArgumentParser
from socket import socket, timeout, AF_INET, SOCK_DGRAM
from select import poll, POLLIN
from random import randint
from os.path import isfile, realpath
from sys import argv, stdin, stdout, stderr
from os import dup2, chdir, fork, getpid, system, setsid, remove, umask
from signal import signal, SIGTERM, SIGINT

import atexit
import time

RECV_SIZE = 4096
INIT_PORT = 42069
PID_FILE = "/tmp/" + argv[0].lstrip("./") + ".pid"

VERSION = "0.5.2"
BANNER = """%s v%s
author: parker (https://github.com/BarkerProoks/udp-tunnel)""" % (argv[0].lstrip("./"), VERSION)
HELP = """MODE (local | proxy)     ... required positional argument
  -d, --daemon             ... runs script in the background
  -o, --output <file>      ... sends stdout to <file>
  -h, --host <hostname/ip> ... for local: proxy host, for proxy: host to serve on
  -p, --port <port #>      ... for local: port to connect to locally, for proxy: port to serve on
  -k, --kill               ... kills the script if already running (doesn't require a MODE)
  -v, --verbose            ... print out each packet sent"""

def kill():
    try:
        remove(PID_FILE)
        exit(0)
    except:
        pass

def safe_fork():
    try:
        pid = fork()
        if pid > 0:
            exit(0)
    except OSError:
        print("fork failed")
        exit(1)

def daemonize(output):
    output = realpath(output) if output is not None else None
    # double fork magic ***
    # fork #1
    safe_fork()
    # reset env
    chdir('/')
    setsid()
    umask(0)
    # fork #2
    safe_fork()
    # redirect output to log file if specified
    redirect(output if output is not None else "/dev/null")    
    # set up pidfile (ensure it gets cleaned up)
    with open(PID_FILE, "wt+") as file:
        print(getpid(), file=file)

def redirect(output=None):
    if output is None:
        return
    stdout.flush()
    stderr.flush()
    logfile = open(output, "at+")
    devnull = open("/dev/null", "w")
    dup2(devnull.fileno(), stdin.fileno())
    dup2(logfile.fileno(), stdout.fileno())
    dup2(logfile.fileno(), stderr.fileno())

def send_for_proxy(host):
    tunnel = socket(AF_INET, SOCK_DGRAM, 0)
    try:
        tunnel.connect((host, INIT_PORT))
    except ConnectionRefusedError:
        return None
    tunnel.send(b"ready")
    tunnel.settimeout(1)
    try:
        message = tunnel.recv(2)
        if message != b"ok":
            return None
    except (ConnectionRefusedError, TimeoutError, timeout):
        return None
    tunnel.settimeout(None)
    return tunnel

def wait_for_local(host):
    tunnel = socket(AF_INET, SOCK_DGRAM, 0)
    tunnel.bind((host, INIT_PORT))
    message, address = tunnel.recvfrom(5)
    if message != b"ready":
        print(" x forwarder isn't ready, try again")
        exit(0)
    tunnel.connect(address)
    tunnel.send(b"ok")
    return tunnel, address[0]

def select_port(ports):
    port = randint(40000, 60000)
    if len(ports) >= 20000:
        return None, ports
    while port in ports:
        port = randint(40000, 60000)
    ports.append(port)
    return port, ports

def proxy(host, listen, verbose) -> int:
    print("running internet facing proxy")

    # ports: list of ports so we can check and
    # make sure we aren't assigning the same
    # port
    # clients: a dict that maps incoming address
    # to a new socket
    # sockets: connection pool
    ports = [INIT_PORT, listen] # make sure these two ports arent selected
    clients = {}
    sockets = poll()

    # wait for forwarder to send ready, send back ok
    print(" > waiting for forwarder to connect...")
    tunnel, local = wait_for_local(host)
    print(" + connected to:", local)

    # open door to clients
    print(" > opening server on port:", listen)
    delta = time.time()
    with socket(AF_INET, SOCK_DGRAM, 0) as server:
        server.bind((host, listen))
        sockets.register(server, POLLIN)
        try:
            while 1:
                alpha = time.time()
                # send heartbeat command
                if int(alpha - delta) >= 5:
                    if verbose:
                        print(" > requesting heartbeat")
                    delta = alpha
                    tunnel.send(b"ok?")
                    tunnel.settimeout(5)
                    try:
                        message = tunnel.recv(3)
                        if b"ok!" not in message:
                            print("protocol error")
                            exit(1)
                    except (ConnectionRefusedError, TimeoutError, timeout):
                        print("connection lost")
                        exit(1)
                    tunnel.settimeout(None)

                events = sockets.poll(0.1)
                for fd, event in events:
                    if fd == server.fileno() and event == POLLIN:
                        if verbose:
                            print(" > incoming client data")
                        packet, address = server.recvfrom(RECV_SIZE)
                        if address not in clients:
                            print(" > adding new client:", address)
                            port, ports = select_port(ports)
                            if port is None:
                                print(" ! too many clients (wtf???)")
                                continue
                            clients[address] = socket(AF_INET, SOCK_DGRAM, 0)
                            clients[address].bind((host, port))
                            print(" + client tethered on:", port)
                            tunnel.send(("connect:"+str(port)).encode("utf-8"))
                            print(" > connection request sent")
                            _, tether = clients[address].recvfrom(RECV_SIZE)
                            clients[address].connect(tether)
                            clients[address].send(packet)
                            if verbose:
                                print(" > sending through tunnel")
                            sockets.register(clients[address], POLLIN)
                        else:
                            clients[address].send(packet)
                            if verbose:
                                print(" > sending through tunnel")
                    else:
                        for address, sock in clients.items():
                            if fd == sock.fileno() and event == POLLIN:
                                if verbose:
                                    print(" > fd:", fd, "coming through tunnel for:", address)
                                packet = sock.recv(RECV_SIZE)
                                server.sendto(packet, address)
        except KeyboardInterrupt:
            return 0
        except Exception as e:
            print(e)
    return 0

def local(host, server, verbose) -> int:
    print("running local server forwarder")
    
    tunnel = None
    clients = {}
    sockets = poll()
    server_addr = ("localhost", server)

    print(" > sending ready status...")
    while tunnel is None:
        tunnel = send_for_proxy(host)
    
    print(" + remote proxy connected")
    sockets.register(tunnel, POLLIN)
    
    timeout = time.time()
    try:
        while 1:
 
            if int(time.time() - timeout) > 30:
                print("connection lost")
                exit(1)

            events = sockets.poll(0.1)

            for fd, event in events:
                if fd == tunnel.fileno() and event > 0:
                    print(" > incoming command from proxy")
                    message = tunnel.recv(RECV_SIZE)
                    if b"connect:" in message:
                        try:
                            port = int(message.decode("utf-8").split(':')[1])
                            clients[port] = (socket(AF_INET, SOCK_DGRAM, 0), 
                                             socket(AF_INET, SOCK_DGRAM, 0))
                            clients[port][1].connect(server_addr)
                            clients[port][0].connect((host, port))
                            clients[port][0].send(b"ok")
                            sockets.register(clients[port][0], POLLIN)
                            sockets.register(clients[port][1], POLLIN)
                            print(" + tethered on", port)
                        except ValueError:
                            print(" x protocol error:", message.decode("utf-8"))
                    if b"ok?" in message:
                        if verbose:
                            print(" ! heartbeat requested")
                        # tell tunnel we're ok!
                        tunnel.send(b"ok!")
                        timeout = time.time()
                else:
                    for port, (rsock, lsock) in clients.items():
                        if event == POLLIN:
                            if fd == lsock.fileno():
                                packet = lsock.recv(RECV_SIZE)
                                if verbose:
                                    print(" > incoming from local")
                                    print(packet)
                                rsock.send(packet)
                            elif fd == rsock.fileno():
                                packet = rsock.recv(RECV_SIZE)
                                if verbose:
                                    print(" > incoming from proxy")
                                    print(packet)
                                lsock.sendto(packet, server_addr)
    except KeyboardInterrupt:
        return 0

    return 0

def run(args):
    if args.daemon:
        print("starting in background...")
        daemonize(args.output)
    if args.output and not args.daemon:
        print("redirecting output...")
        redirect(args.output)
    run = { "proxy": proxy,
            "local": local }
    return run[args.mode](args.host, args.port, args.verbose)

def main():

    print(BANNER)
    
    if len(argv) == 1:
        print("use --help for more info")
        exit(0)

    if "--help" in argv:
        print(HELP)
        exit(0)

    if "-k" in argv or "--kill" in argv:
        try:
            with open(PID_FILE, "rt") as file:
                pid = int(file.read().strip())
            print("killing process: %d" % pid)
            system("kill %d" % pid)
            remove(PID_FILE)
        except OSError:
            pass
        exit(0)

    if isfile(PID_FILE):
        print(argv[0], "is already running")
        print("would you like to kill that and start a new process?", end='')
        answer = None
        while answer not in ['Y', 'N', '']:
            answer = input(" [Y/n] ").upper()
            if answer in ["Y", '']:
                with open(PID_FILE, "rt") as file:
                    pid = int(file.read().strip())
                    system("kill %d" % pid)
                remove(PID_FILE)
            elif answer == "N":
                print("okay, cool")
                exit(0)

    atexit.register(kill)
    signal(SIGTERM, kill)
    signal(SIGINT, kill)

    parser = ArgumentParser(add_help=False)
    parser.add_argument("mode", type=str, choices={"proxy", "local"})
    parser.add_argument("-v", "--verbose", dest="verbose", action="store_true")
    parser.add_argument("-d", "--daemon", dest="daemon", action="store_true",
        help="starts tunnel in the background")
    parser.add_argument("-o", "--output", default=None,
        help="optional output file for logging, will disable stdout")
    parser.add_argument("-h", "--host", default="0.0.0.0",
        help="host to listen on if PROXY, host to connect to if LOCAL")
    parser.add_argument("-p", "--port", default=27960, type=int, 
        help="port to listen on if PROXY, port to connect to if LOCAL")

    exit(run(parser.parse_args()))

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nctrl+c detected")
    finally:    
        exit(0)
