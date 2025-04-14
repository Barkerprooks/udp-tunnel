#!/bin/sh
# posix script to minify udptun so it can run a little bit more performant and lean >:)

udptun='./udptun.py'
udptun_min='./udptun.min.py'

if ! [ -f $udptun ]; then
    echo "$udptun not found directory"
    exit 0
fi

cat $udptun                            |
sed '/__version__ = ".*"/ s/"$/-min"/' | 
sed '/__verbose_output\b/d'            |  
sed '/verbose_print\b/d'               |
sed '/^[[:space:]]*#/d'                |
sed '/--verbose\b/d'                   |
sed 's/#.*$//'                         |
sed '/^$/d'                            |
sed '1s/^/#!\/usr\/bin\/env python3\n/' > $udptun_min

chmod +x $udptun_min