# UDP Tunnel

A simple, no-dependancy python script to bridge two network ports together. Built for
port forwarding games which commonly run on the UDP protocol. Tested with _Quake 3_ and _Project Zomboid_.

## Downloading
You just need __Python 3__ installed on both machines, no environments required. Just download
the script and run it with the desired arguments.

You can download it from here.

    wget https://coredumped.info/tools/udptun.py

## Forwarding a port
This script assumes there are two machines involved. The script is required on both machines to function
properly.
- One machine is hosting the service that is unreachable from the internet. A common situation is a game server on personal hardware behind the router's firewall.
- The other machine is usually hosted elsewhere and has a public IP address.
For example, let's say that we have a game server running locally on port `4321`. We 
want to expose this port to the internet.

### Remote Forwarding
On the remote machine, download the script and run it with the `proxy` subcommand. By 
default the service will bind on `0.0.0.0:4300`. You can change the address with `--bind`

    ./udptun.py proxy --forward 0.0.0.0:4321

This will start the listener and open up a public port `4321` that clients can connect to.

### Local Forwarding
On the local machine, download the script and run it with the `local` subcommand. This
one requires an extra argument `--connect` which instructs the local proxy where to
forward traffic. The default port will be used unless otherwise specified.

    ./udptun.py local --forward 127.0.0.1:4321 --connect example.com

This will begin a handshake process that connects the two ends of the tunnel together.

## Get more performance
The full version of this script has a verbose option, which lets the user see all the
packets going through. I understand the checks for these can take some extra cycles and
I am using one of the slowest languages ever, so I decided to release a minified version
along with the full version.

For maximum performance you can download the minified version from here.

    wget https://coredumped.info/tools/udptun.min.py