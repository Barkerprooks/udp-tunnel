#!/bin/sh
# posix script to minify udptun so it can run a little bit more performant and lean >:)

udptun='./udptun.py'
udptun_min='./udptun.min.py'

if ! [ -f $udptun ]; then
    echo "$udptun not found directory"
    exit 0
fi

cat $udptun                 |
sed '/verbose_print\b/d'    |
sed '/__verbose_output\b/d' |  
sed '/--verbose\b/d'        |
sed '/__version__ = ".*"/ s/"$/-min"/' > $udptun_min

chmod +x $udptun_min