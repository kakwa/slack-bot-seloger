supybot-plugin-seloger
======================

slack plugin for seloger

## Description ##

This supybot plugin searches and alerts you in query for any new adds on 
the french website "www.seloger.com".

It's a Quick and Dirty adaptation from [Supybot IRC pluging from seloger](https://github.com/kakwa/supybot-plugin-seloger/)

## License ##

MIT

## Dependancies ##

This plugin relies on:

* python-slackclient
* lxml
* sqlite3
* python3

## Commands ##

Here is the commands list with a few examples:

* `slhelp`: help for this module

```bash
<nickname> !slhelp
```

* `sladdrent <postal code> <min surface> <max price> <min_num_room>`: add a new rent search for you

```bash
<nickname> !sladdrent 59000 20 600 1
<seloger> Done sladd
```

* `sladdbuy <postal code> <min surface> <max price> <min_num_room>`: add a new buy search for you

```bash
<nickname> !sladdbuy 75001 20 6000000000 10
<seloger> Done sladd
```

* `sllist`: list your active searches

```bash
<nickname> !sllist
<seloger> ID: d5671b6f12ebee2449f307513f3c6322 | Surface >= 20 | Loyer <= 600 | cp == 59000 | type ad == 1 | Pieces >= 1
<seloger> ID: 939262a37d935f4e6297de3a7afbf483 | Surface >= 20 | Loyer <= 6000000000 | cp == 75001 | type ad == 2 | Pieces >= 10
<seloger> Done sllist
```

* `sldisable <search ID>`: remove the given search (use sllist to recover the <search ID>)


```bash
<nickname> !sldisable 939262a37d935f4e6297de3a7afbf483 
```

* `!slstatrent <postal code|'all'>`: print some stats about your rent searches

```bash
<nickname> !slstatrent 59000
<seloger> [...]
<seloger> Done slstat
```

* `!slstatbuy <postal code|'all'>`: print some stats about your buy searches

```bash
<nickname> !slstatbuy all
<seloger> [...]
<seloger> Done slstat
```

This plugin replies you and sends you new adds in PM.

## Installation ##

Once the dependencies are installed, just launch it with `SLACK_API_TOKEN` environment set:

```bash
export SLACK_API_TOKEN='xoxp-XXXXXXXXXXXXXXXXXXX'
python3 slack_seloger.py
```

To keep it running, launch it in `screen` or `tmux`.
