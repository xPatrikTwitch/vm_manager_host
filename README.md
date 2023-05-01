__This app is used for monitoring GPUS and VMS on a proxmox host. Both pcie passthrough gpus and virtual gpus are supported!__

(Currently only nvidia gpus are supported, amd and intel should work but no monitoring stats)

How to install:
---
1) Add the community pve repo using ``echo "deb http://download.proxmox.com/debian/pve bullseye pve-no-subscription" >> /etc/apt/sources.list
`` and then ``rm /etc/apt/sources.list.d/pve-enterprise.list`` After that run ``apt update``
2) Install git using ``apt-get install git -y``
3) Clone this repo to your home folder (on proxmox it is ``/root/``) ``git clone https://github.com/xPatrikTwitch/vm_manager_host.git``
4) Move to the directory ``cd vm_manager_host``
5) To install all required apt and pip packages just run ``sh install.sh``
6) To setup the service just run ``sh install_service.sh``
7) After installing the service you should be able to run ``systemctl enable vm_manager_host`` to enable the service
8) After enabling the service run ``systemctl start vm_manager_host`` to start the app. You should be able to get data on http://YOUR_PROXMOX_IP:6050/ (The 6050 is the default port, you can change it in the config file)

How to setup cpu temperature sensor:
---
By defalt the cpu temperature monitoring will be disabled because no sensor is configured, To configure the correct sensor:
1) Run ``python3 list_temperature_sensors.py`` It will output all detected sensors and their temperature values. These are the cpus i tested and their temperature sensors:
```
Amd Ryzen 9 3900X = k10temp
Amd Ryzen 7 5800H = k10temp
Amd Ryzen 5 1600 = k10temp
Intel Pentium Silver J5040 = coretemp
```
2) Edit the ``config.json`` for exmample using nano, Then set the temperature sensor name in ``"cpu_temperature_sensor": ""``
3) Run ``systemctl restart vm_manager_host`` to restart the app


Other config options:
---
``"api_port": 6050`` The api host port

``"gpu_passthrough_vm_ip": []`` The IP of a vm that uses gpu passthrough (used with VM_Manager_Guest), This is an example: ``[["100","10.0.0.169:6050"]]`` First part is the vm ID and second is the IP and Port

``"gpu_ignore": []`` List of gpu pci id's that are ignored and not monitored, This is an example: ``"gpu_ignore": ["0000:04:00.0"]``
 
``"gpu_power_limit_override": []`` List of gpu pci id's and power limit values (useful for laptop gpus that dont report their power limit) This is an example: ``"gpu_power_limit_override": [["0000:01:00.0", "80"]]`` First part is the gpu pci id and second is the power limit value

The last two config values do not need to be changed
``"profile_file_path": "/etc/vgpu_unlock/profile_override.toml"``
``"qemu_process_path": "/run/qemu-server"``

*After any config change run ``systemctl restart vm_manager_host`` to restart the app

This is a config that i use with one of my proxmox servers
---
```
{
    "api_port": 6050,
    "gpu_passthrough_vm_ip": [["201","10.0.0.169:6050"]],
    "gpu_ignore": ["0000:04:00.0"],
    "gpu_power_limit_override": [["0000:01:00.0", "80"]],
    "cpu_temperature_sensor": "k10temp",
    "profile_file_path": "/etc/vgpu_unlock/profile_override.toml",
    "qemu_process_path": "/run/qemu-server"
}
```

If your gpu is showing up as a unknown device you can try updating the pci.ids using ``sh update_pci_ids.sh`` After that you will need to restart the app again using ``systemctl restart vm_manager_host``

**This is not the best code (It's actually one of my first time working with python and on linux) but works for me...*