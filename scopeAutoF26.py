from ctypes import *
from dwfconstants import *
import matplotlib.pyplot as plt
import csv
from sys import path
from os import makedirs
from datetime import datetime
import argparse
import sys
import time
import datetime
import os
from scipy.signal import butter, sosfiltfilt

# ===== CONSTANTS =====

frequency = 24 * 1000 * 1000

lowcut = 1 * 1000 * 1000
highcut = 3 * 1000 * 1000

def samplesFromNs(ns):
    return frequency * ns * 10e-9

samples = 150
duration = samples/frequency

cycles = 10
interval = 0.1

triglevel = 1.0
# Percent to shift the trigger onscreen. 0.5 moves it to the left edge.
trigoffsetpc = 0.6
# Think of this as the delay between the trigger signal and the start of the capture.
# With trigoffsetpc = 0.5, it's the gap between the trigger and the left edge of the plot.
# NOTE: This breaks the code if set to anything other than 0, for some reason. I genuinely have no idea why.
# In the meantime, don't use it.
trigoffsetns = 0
# Horizontal position of the trigger. Positive values move it to the left and vice versa.
trigpos = (duration * trigoffsetpc) + (trigoffsetns * (10e-9))

# Initialize parameters with default values
path = "./outputs"
dataset = "misc"
temperature = 0.0
force = 0.0
comment = None

plot = True

pvref = 0.15
nvref = -0.1
vcm = round((pvref + nvref) / 2, 8)
lsb = (pvref - nvref) / 4096

# ===== Program initialization =====

if sys.platform.startswith("win"):
    dwf = cdll.dwf
elif sys.platform.startswith("darwin"):
    dwf = cdll.LoadLibrary("/Library/Frameworks/dwf.framework/dwf")
else:
    dwf = cdll.LoadLibrary("libdwf.so")

parser = argparse.ArgumentParser(
    prog='scopeAutoF26',
    description='Ultrasound data capture script',
    epilog='Stuck? Contact tomasini@uw.edu'
)

# Parameters
parser.add_argument('-p', '--path', help="Path to the output directory")
parser.add_argument('-d', '--dataset', help="User-defined dataset flag")
parser.add_argument('-t', '--temperature', help="Specimen temperature in degrees Celsius")
parser.add_argument('-f', '--force', help="Static contact force in newtons")
parser.add_argument('-c', '--comment', help="Additional remarks (optional)")


args = parser.parse_args()

if args.path != None:
    path = args.path
else:
    print("Using default path " + path)
if args.dataset != None:
    dataset = args.dataset
else:
    print("Using default dataset " + dataset)
if args.temperature != None:
    temperature = args.temperature
else:
    print(f"Using default temperature {temperature} C")
if args.force != None:
    force = args.force
else:
    print(f"Using default force {force} N")
if args.comment != None: comment = args.comment

# ===== Acquire AD2 =====

# declare variables
hdwf = c_int()
cDevice = c_int()
 
# declare string variables
szerr = create_string_buffer(512)
sz0 = create_string_buffer(256)
sz1 = create_string_buffer(256)

devicename = create_string_buffer(64)
serialnum = create_string_buffer(16)
 
# print(DWF version
version = create_string_buffer(16)
dwf.FDwfGetVersion(version)
print("DWF Version: "+str(version.value))
 
# enumerate connected devices
dwf.FDwfEnum(c_int(0), byref(cDevice))
print("Number of Devices: "+str(cDevice.value))
 
# open devices
for iDevice in range(0, cDevice.value):
    dwf.FDwfEnumDeviceName(c_int(iDevice), devicename)
    dwf.FDwfEnumSN(c_int(iDevice), serialnum)
    # if(serialnum.value == b'SN:210415BD66A3'):
    if(True):
        print("------------------------------")
        print("Device "+str(iDevice+1)+" : ")
        print("\t" + str(devicename.value))
        print("\t" + str(serialnum.value))
        dwf.FDwfDeviceOpen(c_int(iDevice), byref(hdwf))
        if hdwf.value == 0:
            szerr = create_string_buffer(512)
            dwf.FDwfGetLastErrorMsg(szerr)
            print(szerr.value)

# ===== Initialize AD2 =====

dwf.FDwfDeviceAutoConfigureSet(hdwf, c_int(0))
dwf.FDwfAnalogInChannelEnableSet(hdwf, c_int(-1), c_int(1))
dwf.FDwfAnalogInFrequencySet(hdwf, c_double(frequency))
dwf.FDwfAnalogInChannelRangeSet(hdwf, c_int(-1), c_double(10))
dwf.FDwfAnalogInBufferSizeSet(hdwf, c_int(samples))
dwf.FDwfAnalogInChannelFilterSet(hdwf, c_int(-1), filterDecimate)
dwf.FDwfAnalogInConfigure(hdwf, c_int(1), c_int(0))

dwf.FDwfAnalogInTriggerSourceSet(hdwf, trigsrcDetectorAnalogIn)
dwf.FDwfAnalogInTriggerChannelSet(hdwf, c_int(1))
dwf.FDwfAnalogInTriggerTypeSet(hdwf, trigtypeEdge)
dwf.FDwfAnalogInTriggerPositionSet(hdwf, c_double(trigpos))
dwf.FDwfAnalogInTriggerLevelSet(hdwf, c_double(triglevel))

print("Waiting for voltage to stabilize...")
time.sleep(2)
print("Done")

dwf.FDwfAnalogInConfigure(hdwf, c_int(1), c_int(1))

# ===== Initialize file =====

filetimestamp = datetime.datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d_%Hh%Mm%Ss')
filename = f"{path}/{dataset}/{filetimestamp}.csv"

os.makedirs(f"{path}/{dataset}", exist_ok = True)

totalData = [[None for _ in range(samples)] for _ in range(cycles)]

with open(filename, "w", newline="") as f:
    f.write(f"# Dataset: {dataset}\n")
    f.write(f"# N: {samples}\n")
    f.write(f"# Step size: {round(1/frequency, 5)}\n")
    f.write(f"# Cycles: {cycles}\n")
    f.write(f"# VCM: {vcm}\n")
    f.write(f"# Temperature: {temperature}C\n")
    f.write(f"# Force: {force}\n")
    f.write(f"# Remarks: {comment}\n")
    writer = csv.writer(f)

    xtimestamps = []
    ylevel = []

# ===== Run the capture cycles =====

    populated = False
    i = 0
    while i < cycles:
        # print("Starting capture " + str(i + 1) + "...")

        f.write(f"# ==== CAPTURE {i + 1} ====\n")
        writer.writerow(["Timestamp","Level","OR"])

        sts = c_byte()

        while True:
            dwf.FDwfAnalogInStatus(hdwf, c_int(1), byref(sts))
            if sts.value == DwfStateDone.value :
                break
            # time.sleep(0.1)
        # print("Complete")
        
        # Fetch the data from the buffer. 
        timestamp = 0
        rgdSamples0 = (c_double*samples)()
        rgdSamples1 = (c_double*samples)()
        dwf.FDwfAnalogInStatusData(hdwf, 0, rgdSamples0, samples) # get channel 1 data
        dwf.FDwfAnalogInStatusData(hdwf, 1, rgdSamples1, samples) # get channel 2 data

        # Convert numeric voltage reading to equivalent ADC output
        def convertValue(level):
            val = level - vcm

            if level < (nvref - (lsb / 2)): return -2048, 1
            if level > (pvref - (lsb / 2)): return 2047, 1

            val = (val / (pvref - nvref)) * 4096
            return val, 0
        
        # Bandpass filter
        sos = butter(4, [lowcut, highcut], btype = 'bandpass', output = 'sos', fs = frequency)
        rgdSamples0 = sosfiltfilt(sos, rgdSamples0)

        # Write data to file
        j = 0
        for value in rgdSamples0:
            level, orind = convertValue(value)
            writer.writerow([timestamp, level, orind])
            # Populate data arrays for visualization
            if plot: totalData[i][j] = level
            if plot and not populated:
                xtimestamps.append(timestamp)
                ylevel.append(level)
            timestamp += 1
            j += 1
        populated = True

        # print("Data written to file " + filename + "\n")

        time.sleep(interval)
        i += 1

    # Take the average of all captures
    average = [None] * samples
    i = 0
    timestamp = 0
    writer.writerow(["# ==== AVERAGE ===="])
    while i < samples:
        tally = 0
        j = 0
        while j < cycles:
            tally += totalData[j][i]
            j += 1
        average[i] = tally / cycles
        writer.writerow([timestamp, average[i], 0])
        timestamp += 1
        i += 1

print("Data written to file " + filename + "\n")
dwf.FDwfDeviceCloseAll()

# ===== Plot data =====
# TODO: Maybe plot the average of all captures?
if plot:
    plt.plot(xtimestamps, average, '-')

    plt.xticks(rotation = 30)
    plt.xlabel('Time')
    plt.ylabel('Level')
    plt.title(f'{filename}', fontsize = 18)
    plt.grid()
    plt.legend()
    plt.show()

sys.exit()