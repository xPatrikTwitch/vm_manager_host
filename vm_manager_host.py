import gi
from gi.repository import GObject,GLib
from operator import truediv, truth
from pickle import FALSE
from threading import Thread
import json
import requests
import subprocess
import math
import os
import tomli
import re
import flask
import psutil
import requests
import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

app = flask.Flask(__name__)

app_version = "1.0.1"

class Service:
    def __init__(self):
        #config
        self.api_port = 6050
        self.gpu_passthrough_vm_ip = [] #[["VM_ID","VM_IP:VM_PORT"],["VM_ID","VM_IP:VM_PORT"]]
        self.gpu_ignore = [] #["GPU_PCI_ID","GPU_PCI_ID"]
        self.gpu_power_limit_override = [] #[["GPU_PCI_ID", "VALUE"],["GPU_PCI_ID", "VALUE"]]
        self.cpu_temperature_sensor = ""
        self.profile_file_path = "/etc/vgpu_unlock/profile_override.toml"
        self.qemu_process_path = "/run/qemu-server"
        
        if (os.path.isfile("/root/vm_manager_host/config.json")):
            self.config_read()
        else:
            self.config_create()

        self.gpu_list = []
        self.pci_ids_data = []
        self.load_pci_ids()
        print("----------------------------------------")
        print("Gpu devices:")
        for pci_device in os.listdir("/sys/bus/pci/devices"):
            with open("/sys/bus/pci/devices/" + pci_device + "/class", mode="r") as class_file:
                if (class_file.read().strip() == "0x030000"):
                    vendor = open("/sys/bus/pci/devices/" + pci_device + "/vendor", mode="r").read().strip().lstrip("0x")
                    device = open("/sys/bus/pci/devices/" + pci_device + "/device", mode="r").read().strip().lstrip("0x")
                    mdev = os.path.isdir("/sys/bus/pci/devices/" + pci_device + "/mdev_supported_types")
                    device_name = self.get_device_name(vendor, device)
                    if (pci_device in self.gpu_ignore):
                        print("[IGNORED] " + pci_device + " | " + device_name + " | mdev:" + str(mdev))
                    else:
                        self.gpu_list.append([pci_device, device_name, mdev, vendor, device])
                        print(pci_device + " | " + device_name + " | mdev:" + str(mdev))
        print("----------------------------------------")
        
        print("Passthrough VM IP:")
        for vm in self.gpu_passthrough_vm_ip:
            print(vm[0] + " | " + vm[1])
        print("----------------------------------------")

        global host_name
        with open("/etc/hostname", mode="r") as host_name_file:
            host_name = host_name_file.read().strip()

        #Get data before api start
        self.get_system_info()
        self.get_gpu_info()
        GLib.timeout_add(1000, self.get_system_info)
        GLib.timeout_add(1000, self.get_gpu_info)
        
        #Start api
        thread = Thread(target=self.api_run)
        thread.start()

    def config_create(self):
        with open ("/root/vm_manager_host/config.json", "w") as config_file:
            json_dict = {'api_port': self.api_port,'gpu_passthrough_vm_ip': self.gpu_passthrough_vm_ip, 'gpu_ignore': self.gpu_ignore,'gpu_power_limit_override': self.gpu_power_limit_override, 'cpu_temperature_sensor': self.cpu_temperature_sensor, 'profile_file_path': self.profile_file_path, 'qemu_process_path': self.qemu_process_path}
            json_string = json.dumps(json_dict, indent=4)
            config_file.write(json_string) 

    def config_read(self):
        try:
            with open ("/root/vm_manager_host/config.json", "r") as config_file:
                config_file_json = json.loads(config_file.read())
                self.gpu_passthrough_vm_ip = config_file_json["gpu_passthrough_vm_ip"]
                self.api_port = config_file_json["api_port"]
                self.gpu_ignore = config_file_json["gpu_ignore"]
                self.gpu_power_limit_override = config_file_json["gpu_power_limit_override"]
                self.cpu_temperature_sensor = config_file_json["cpu_temperature_sensor"]
                self.profile_file_path = config_file_json["profile_file_path"]
                self.qemu_process_path = config_file_json["qemu_process_path"]
        except:
            print("Error reading config file")            

    def load_pci_ids(self):
        regex1 = re.compile(r'(?P<vendor>[a-z0-9]{4})\s+(?P<vendor_name>.*)')
        regex2 = re.compile(r'\t(?P<device>[a-z0-9]{4})\s+(?P<device_name>.*)')
        regex3 = re.compile(r'\t\t(?P<subvendor>[a-z0-9]{4})\s+(?P<subdevice>[a-z0-9]{4})\s+(?P<subsystem_name>.*)')
        with open("/usr/share/misc/pci.ids", "r") as fp:
            for line in fp:
                m = regex1.match(line)
                if m:
                    d = m.groupdict()
                    d['devices'] = []
                    self.pci_ids_data.append(d)
                else:
                    m = regex2.match(line)
                    if m:
                        d = m.groupdict()
                        d['subdevices'] = []
                        self.pci_ids_data[-1]['devices'].append(d)
                    else:
                        m = regex3.match(line)
                        if m:
                            self.pci_ids_data[-1]['devices'][-1]['subdevices'].append(m.groupdict())

    def get_device_name(self, vendor, device):
        for vendor_entry in self.pci_ids_data:
            if (vendor_entry["vendor"] == vendor):
                for device_entry in vendor_entry["devices"]:
                    if (device_entry["device"] == device):
                        return(device_entry["device_name"])
        if (vendor == "10de"): vendor_name = "Nvidia"
        if (vendor == "1002"): vendor_name = "Amd"
        if (vendor == "8086"): vendor_name = "Intel"
        return vendor_name + " Unknown Device" + " (" + vendor + ":" + device + ")"

    def get_gpu_info(self):
        running_vm = []
        for file in os.listdir(self.qemu_process_path):
            if (file.endswith(".pid")):
                vm_id = file.split('.')[0]
                if (vm_id not in running_vm):
                    running_vm.append(file.replace(".pid",""))

        gpu_info_new = []
        for gpu in self.gpu_list:
            if (gpu[2] == True): #mdev gpu
                if (gpu[3] == "10de"): #nvidia
                    smi_output = subprocess.check_output('nvidia-smi -i ' + gpu[0] + ' --query-gpu=name,power.draw,power.limit,memory.used,memory.total,temperature.gpu,fan.speed --format=csv,noheader', shell=True, text=True)
                    smi_output = smi_output.replace("[N/A]", "0") #some gpus (usually laptop ones) dont report power and fan
                    smi_output_split = smi_output.split(",")
                    this_gpu_name = smi_output_split[0].strip()
                    this_gpu_power_draw = str(re.findall('\d+', smi_output_split[1])[0])
                    this_gpu_power_limit = str(re.findall('\d+', smi_output_split[2])[0])
                    this_gpu_memory_usage = str(re.findall('\d+', smi_output_split[3])[0])
                    this_gpu_memory_total = str(re.findall('\d+', smi_output_split[4])[0])
                    this_gpu_temperature = str(re.findall('\d+', smi_output_split[5])[0])
                    this_gpu_fan = str(re.findall('\d+', smi_output_split[6])[0])

                    for gpu_power_limit in self.gpu_power_limit_override:
                        if gpu[0] == gpu_power_limit[0]:
                            this_gpu_power_limit = gpu_power_limit[1]

                    this_gpu_vm = []
                    for vm in running_vm:
                        with open("/etc/pve/qemu-server/" + vm + ".conf", mode="r") as vm_config_file:
                            vm_config = vm_config_file.read()
                            if (gpu[0] in vm_config) or (str(gpu[0]).split(".")[0] in vm_config):
                                if (os.path.isfile(self.profile_file_path)):
                                    with open(self.profile_file_path, mode="rb") as profile_file:
                                        toml = tomli.load(profile_file)
                                        try:
                                            if (vm in toml["vm"]): #if vm has profile override get vgpu memory size
                                                raw_framebuffer = toml["vm"][vm]["framebuffer"]
                                                raw_framebuffer_reservation = toml["vm"][vm]["framebuffer_reservation"]
                                                string_memory_size = str(math.floor((raw_framebuffer / 1024 / 1024) + (raw_framebuffer_reservation / 1024 / 1024)))
                                                this_gpu_vm.append({"vm_id": vm, "vm_state": "1", "vm_gpu_memory": string_memory_size})
                                            else: #get vgpu memory size from mdev profile
                                                with open("/sys/bus/pci/devices/" + gpu[0] + "/00000000-0000-0000-0000-" + vm.zfill(12) + "/mdev_type/description", mode="r") as vgpu_profile_file:
                                                    this_gpu_vm.append({"vm_id": vm, "vm_state": "1", "vm_gpu_memory": str(re.findall('\d+', vgpu_profile_file.read().split(",")[2].strip())[0])})
                                        except: #get vgpu memory size from mdev profile
                                            with open("/sys/bus/pci/devices/" + gpu[0] + "/00000000-0000-0000-0000-" + vm.zfill(12) + "/mdev_type/description", mode="r") as vgpu_profile_file:
                                                    this_gpu_vm.append({"vm_id": vm, "vm_state": "1", "vm_gpu_memory": str(re.findall('\d+', vgpu_profile_file.read().split(",")[2].strip())[0])})
                                else: #get vgpu memory size from mdev profile
                                    with open("/sys/bus/pci/devices/" + gpu[0] + "/00000000-0000-0000-0000-" + vm.zfill(12) + "/mdev_type/description", mode="r") as vgpu_profile_file:
                                        this_gpu_vm.append({"vm_id": vm, "vm_state": "1", "vm_gpu_memory": str(re.findall('\d+', vgpu_profile_file.read().split(",")[2].strip())[0])})

                    gpu_info_new.append({"gpu_name": this_gpu_name, "gpu_pci_id": gpu[0], "gpu_mdev": str(gpu[2]), "gpu_vendor": gpu[3], "gpu_device": gpu[4], "gpu_power_draw": this_gpu_power_draw, "gpu_power_limit": this_gpu_power_limit, "gpu_memory_usage": this_gpu_memory_usage, "gpu_memory_total": this_gpu_memory_total, "gpu_temperature": this_gpu_temperature, "gpu_fan": this_gpu_fan, "gpu_vm": this_gpu_vm })
                
                if (gpu[3] == "1002"): #amd (no monitoring)
                    gpu_info_new.append({"gpu_name": gpu[1], "gpu_pci_id": gpu[0], "gpu_mdev": str(gpu[2]), "gpu_vendor": gpu[3], "gpu_device": gpu[4], "gpu_power_draw": "0", "gpu_power_limit": "0", "gpu_memory_usage": "0", "gpu_memory_total": "0", "gpu_temperature": "0", "gpu_fan": "0", "gpu_vm": [] })
                
                if (gpu[3] == "8086"): #intel (no monitoring)
                    gpu_info_new.append({"gpu_name": gpu[1], "gpu_pci_id": gpu[0], "gpu_mdev": str(gpu[2]), "gpu_vendor": gpu[3], "gpu_device": gpu[4], "gpu_power_draw": "0", "gpu_power_limit": "0", "gpu_memory_usage": "0", "gpu_memory_total": "0", "gpu_temperature": "0", "gpu_fan": "0", "gpu_vm": [] })
            else: #passthrough
                this_gpu_vm = []
                this_gpu_name = gpu[1]
                this_gpu_power_draw = "0"
                this_gpu_power_limit = "0"
                this_gpu_memory_usage = "0"
                this_gpu_memory_total = "0"
                this_gpu_temperature = "0"
                this_gpu_fan = "0"
                for vm in running_vm:
                    with open("/etc/pve/qemu-server/" + vm + ".conf", mode="r") as vm_config_file:
                            vm_config = vm_config_file.read()
                            if (gpu[0] in vm_config) or (str(gpu[0]).split(".")[0] in vm_config):
                                vm_has_ip = False
                                for vm_ip in self.gpu_passthrough_vm_ip:
                                    if (vm == vm_ip[0]): #vm id has an ip in config, attemp to get data
                                        try:
                                            vm_has_ip = True
                                            response = requests.get("http://" + vm_ip[1], timeout=1)
                                            response_json = response.json()
                                            this_gpu_name = str(response_json["gpu_name"])
                                            this_gpu_power_draw = response_json["gpu_power_draw"]
                                            this_gpu_power_limit = response_json["gpu_power_limit"]
                                            this_gpu_memory_usage = response_json["gpu_memory_usage"]
                                            this_gpu_memory_total = response_json["gpu_memory_total"]
                                            this_gpu_temperature = response_json["gpu_temperature"]
                                            this_gpu_fan = response_json["gpu_fan"]

                                            for gpu_power_limit in self.gpu_power_limit_override:
                                                if gpu[0] == gpu_power_limit[0]:
                                                    this_gpu_power_limit = gpu_power_limit[1]
                                            
                                            this_gpu_vm.append({"vm_id":vm, "vm_state":"1", "vm_gpu_memory":this_gpu_memory_total})
                                        except:
                                            this_gpu_vm.append({"vm_id":vm, "vm_state":"1", "vm_gpu_memory":this_gpu_memory_total})
                                if (vm_has_ip == False):
                                    this_gpu_vm.append({"vm_id":vm, "vm_state":"1", "vm_gpu_memory":this_gpu_memory_total})

                gpu_info_new.append({"gpu_name": this_gpu_name, "gpu_pci_id": gpu[0], "gpu_mdev": str(gpu[2]), "gpu_vendor": gpu[3], "gpu_device": gpu[4], "gpu_power_draw": this_gpu_power_draw, "gpu_power_limit": this_gpu_power_limit, "gpu_memory_usage": this_gpu_memory_usage, "gpu_memory_total": this_gpu_memory_total, "gpu_temperature": this_gpu_temperature, "gpu_fan": this_gpu_fan, "gpu_vm": this_gpu_vm })

        global gpu_info
        gpu_info = gpu_info_new
        return True
    
    def get_system_info(self):
        global cpu_name
        global cpu_usage
        global cpu_frequency
        global cpu_temperature
        global ram_usage
        global ram_total

        with open("/proc/cpuinfo", mode="r") as cpu_info_file:
            cpu_info = cpu_info_file.read()

        for line in cpu_info.split('\n'):
            if "model name" in line:
                cpu_name = re.sub(".*model name.*:", "", line,1)
            if "cpu MHz" in line:
                cpu_frequency = str(int(float(re.sub(".*cpu MHz.*:", "", line,1))))

        cpu_usage = str(psutil.cpu_percent())
        if (self.cpu_temperature_sensor != ""): cpu_temperature = str(math.floor(psutil.sensors_temperatures()[self.cpu_temperature_sensor][0][1]))
        else: cpu_temperature = 0
        
        ram_usage = str(round(psutil.virtual_memory().used / 1024 / 1024 / 1024, 1))
        ram_total = str(round(psutil.virtual_memory().total / 1024 / 1024 / 1024, 1))
        return True
    
    def api_run(self):
        print("Starting api host on " + "0.0.0.0:" + str(self.api_port))
        app.run(host='0.0.0.0', port=self.api_port)
    
    @app.route('/', methods=['GET'])
    def response():
        json_dict = {'app_version':app_version, 'host_name':host_name, 'cpu_name':cpu_name, 'cpu_usage':cpu_usage, 'cpu_frequency':cpu_frequency, 'cpu_temperature':cpu_temperature, 'ram_usage':ram_usage, 'ram_total':ram_total, 'gpu':gpu_info}
        json_string = json.dumps(json_dict, indent=4)
        return json_string
        
def main():
    Service()
    mainloop = GLib.MainLoop()
    mainloop.run()

if __name__ == "__main__":
    main()