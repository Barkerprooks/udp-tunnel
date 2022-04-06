# UDP Tunnel v0.5.2 - A simple reverse proxy for IOQuake3
This script uses the primitive socket API and posix "select" functionality to create an asynchronous UDP reverse proxy. This proxy is designed specifically for ioquake3, but it will probably work
with other games or programs. There are no dependancies, just make sure python3 is installed

# How to use
### Download the script
```
wget https://raw.githubusercontent.com/Barkerprooks/udp-tunnel/main/udp-tunnel && chmod +x udp-tunnel
```
### On the remote side (proxy, internet facing server, etc)
`./udp-tunnel proxy -p <listen port>`\
this will open an internet facing port on \<listen port\>
### On the local side (home server, raspberry pi, etc)
`./udp-tunnel local -h <proxy host> -p <local port>`\
this will connect to the proxy, and the local service to forward
