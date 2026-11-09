# LernZeit

Web-App für das Schulportal Hessen: Stundenplan, „Mein Unterricht“, Vertretungsplan, Kalender und manuelle Aufgaben mit Erinnerungen am Vortag.

## Lokal starten

Python 3.11 oder neuer wird benötigt. Im Projektordner in PowerShell:

```powershell
py -3 -m pip install -r requirements-web.txt
py -3 web\\server.py
```

Dann `http://127.0.0.1:8765` im Browser öffnen. Die Portalzugangsdaten werden nur während der Sitzung im Serverspeicher gehalten. Eigene Aufgaben werden lokal im Browser gespeichert.

## Datenschutz bei gehosteter Nutzung

Bei einer gehosteten Version werden die Portalzugangsdaten über HTTPS an den App-Server übertragen und dort während der Sitzung verarbeitet. Sie werden nicht dauerhaft gespeichert. Eigene Aufgaben bleiben im Browser. Sitzungen enden bei einem Neustart des Servers.
