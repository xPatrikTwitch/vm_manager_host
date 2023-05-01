mv /usr/share/misc/pci.ids /usr/share/misc/pci.ids.backup
curl https://pci-ids.ucw.cz/v2.2/pci.ids -O --output-dir /usr/share/misc/
