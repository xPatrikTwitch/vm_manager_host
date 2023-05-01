import psutil
print("----------------------------------------")
data = psutil.sensors_temperatures()
print(data)
print("----------------------------------------")
for sensor in data:
    print(sensor)
print("----------------------------------------")