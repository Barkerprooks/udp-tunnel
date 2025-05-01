# UDP Tunnel

A python script to bridge two network ports together. No dependencies required. Built for
port forwarding games which commonly run on the UDP protocol. Tested with _Quake 3_ and _Project Zomboid_.

## Downloading
You just need __Python 3__ installed on both machines, no environments required. Just download
the script and run it with the desired arguments.

Run this command to download the script.
#### Linux
    curl -O udptun.py https://coredumped.info/utils/udptun.py
#### Windows (Powershell)
    irm https://coredumped.info/utils/udptun.py | out-file udptun.py -encoding UTF8

## Forwarding a Port
This script assumes there are two machines involved. The script is required on both machines to function
properly.
- One machine is hosting the service that is unreachable from the internet. A common situation is a game server on personal hardware behind the router's firewall.
- The other machine is usually hosted elsewhere and has a public IP address.
For example, let's say that we have a game server running locally on port `4321`. We 
want to expose this port to the internet.
- Let's say our public machine is hosted at `example.com`. 

### Remote Forwarding

On the remote machine, download the script and run it with the `proxy` subcommand. By 
default the service will bind on `0.0.0.0:4300`. 

Use `--forward` or `-f` to bind the address we want players to connect to.

    python udptun.py proxy --forward 0.0.0.0:4321

This will start the listener and open up a public port `4321` that clients can connect to.

#### Change the Default Communication Port
Change the routing service address with `--bind` or `-b`. This command will change it to public port `4444`

    python udptun.py proxy --forward 0.0.0.0:4321 --bind 0.0.0.0:4444

### Local Forwarding
On the local machine, download the script and run it with the `local` subcommand. This
one requires an extra argument `--connect` which instructs the local proxy where to
forward traffic. The default port will be used unless otherwise specified.

    python udptun.py local --forward 127.0.0.1:4321 --connect example.com

This will begin a handshake process that connects the two ends of the tunnel together.
#### Change the Default Communication Port
If you change the default port to `4444` on the proxy side, you'll need to change it on the local side. In the `--connect`
option, use a full address like this.

    python updtun.py local --forward 127.0.0.1:4321 --connect example.com:4444

## Get More Performance
The full version of this script has a verbose option, which lets the user see all the
packets going through. I understand the checks for these can take some extra cycles and
I am using one of the slowest languages ever, so I decided to release a minified version
along with the full version.

Run this command to download the minified script.
#### Linux
    curl -O udptun.min.py https://coredumped.info/utils/udptun.min.py
#### Windows (Powershell)
    irm https://coredumped.info/utils/udptun.min.py | out-file udptun.min.py -encoding UTF8
