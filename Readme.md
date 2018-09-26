# Deutsche Bahn Sparpreisbot

Mit diesem Telegram Bot ist es möglich, Sparpreisangebote einfach über Telegram zu finden und zu überwachen.
Es ist einfach möglich, nach Dauer, Preis und Umsteigen zu filtern, genau wie auf der Website. Zusätzlich 
wird automatisch die erste und zweite Klasse überprüft und man kann schnell zur vorherigen und nächsten Woche
sowie zum vorherigen und nächsten Tag springen.

Ursprünglich war geplant, automatische Benachrichtigungen einzubauen, das ist aber nicht ganz fertig geworden.

Da es rechtlich nicht erlaubt ist, auf die APIs der Sparpreissuche zuzugreifen, ist der Bot nicht weiterentwickelt
worden oder öffentlich zugänglich. Für andere Projekte oder private Zwecke wird daher hier der Quellcode
zur Verfügung gestellt, in der Hoffnung, dass er doch noch einen Sinn erfüllt.

## Einrichtung
Im Ordner config muss die Datei config.ini erstellt werden, die folgende Form hat:
```[DEFAULT]
BotToken=<Hier einfügen>
WebhookUrl=<Hier einfügen>
Port=<Hier einfügen>
```

Die WebhookUrl muss zu einer mit https abgesicherten URL zeigen, die dann mit einem reverse-proxy (z.B. nginx, Apache)
auf den angegebenen Port weiterleitet.

Der Daemon kann dann manuell über die Kommandozeile gestartet werden, für längerfristigen Betrieb ist zumindest
die Verwendung von `screen` oder besser eines `systemd` services zu empfehlen.

Alle Nutzerdaten werden in der Datenbank config/bahn.sqlite gespeichert, die beim ersten Start erstellt wird.