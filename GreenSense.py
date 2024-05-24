#!/frederick-cet4925/bin/python3

from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTClient
import os
import smbus
import RPi.GPIO as GPIO
import time
import urllib.request
import json
import urllib.parse

# AWS IoT configurations
host = "a2wag89oq9j5cr-ats.iot.us-east-1.amazonaws.com"
root_ca_path = "/home/frederick-cet4925/Desktop/GreenSense - Final Project/Amazon Root CA Certificates/AmazonRootCA1.pem"
certificate_path = "/home/frederick-cet4925/Desktop/GreenSense - Final Project/Device Certificate/4dec8aed2bf2f00804b93ea1879a0bd694b5dead07fac21702fbb99c344f8005-certificate.pem.crt"
private_key_path = "/home/frederick-cet4925/Desktop/GreenSense - Final Project/Private Key File/4dec8aed2bf2f00804b93ea1879a0bd694b5dead07fac21702fbb99c344f8005-private.pem.key"
client_id = "Green_Sense_Project"
topic = "MyTopics/SensorData"

# Define the I2C address of the ADS1115
ADC_ADDRESS = 0x48

# ADS1115 Registers
ADS1115_CONVERSION_REG = 0x00
ADS1115_CONFIG_REG = 0x01

# Create an instance of the smbus
bus = smbus.SMBus(1)  # Assuming Raspberry Pi 3/4 with I2C bus 1

# Set up GPIO mode
GPIO.setmode(GPIO.BCM)  # Use BCM pin numbering
GPIO.setwarnings(False)  # Disable warnings

# Define the GPIO pin for the relay
relay_pin = 27  

# Set up the GPIO pin as an output
GPIO.setup(relay_pin, GPIO.OUT)

# Main function
def main():
    aws_client = configure_aws_client()
    
    try:
        while True:
            # Read and print sensor data
            moisture_percentage = read_sensors()
            # Get weather data
            api_key = "fc9695c224199c77c0ea2bf0755bb14f"
            city = "New York City"
            weather_data = get_weather(api_key, city)
            # Control the relay/valve based on moisture and weather data
            valve_state = control_valve(moisture_percentage, weather_data)
            # Print valve state
            print(f"Valve is {valve_state}")

            # Print weather information
            if isinstance(weather_data, dict):
                print(f"Weather in {weather_data['city']}:")
                print(f"Temperature: {weather_data['temperature_celsius']}°C / {weather_data['temperature_fahrenheit']}°F")
                print(f"Description: {weather_data['description']}")
                
                # Check temperature status and alert if freezing
                if weather_data["temperature_status"] == "Freezing":
                    print("WARNING: Freezing temperature detected!")
                    
            else:
                print(weather_data)
            
            # Prepare message payload
            message = {
                "moisture_percentage": moisture_percentage,
                "valve_state": valve_state,
                "weather": weather_data
            }
            message_json = json.dumps(message)

            # Publish message to AWS IoT
            publish_to_aws(aws_client, topic, message_json)
            
            time.sleep(10)  # Wait before the next cycle

    except KeyboardInterrupt:
        print("Program terminated by user.")
    finally:
        GPIO.cleanup()
        print("GPIO cleanup completed")

def configure_aws_client():
    client = AWSIoTMQTTClient(client_id)
    client.configureEndpoint(host, 8883)
    client.configureCredentials(root_ca_path, private_key_path, certificate_path)
    client.configureAutoReconnectBackoffTime(1, 32, 20)
    client.configureOfflinePublishQueueing(-1)
    client.configureDrainingFrequency(2)
    client.configureConnectDisconnectTimeout(10)
    client.configureMQTTOperationTimeout(5)
    return client

# Function to configure the ADS1115
def configure_ads1115(channel):
    # Single-ended input channel configuration
    # AIN0 = 0x4000, AIN1 = 0x5000, AIN2 = 0x6000, AIN3 = 0x7000
    config_map = {
        0: 0x4000,
        1: 0x5000,
        2: 0x6000,
        3: 0x7000,
    }

    # Set configuration parameters (for single-shot mode, 4.096V, 128SPS)
    config = 0x8000  # Operational status/single-shot conversion start
    config |= config_map[channel]  # MUX configuration
    config |= 0x0100  # +/-4.096V range
    config |= 0x0080  # Continuous conversion mode
    config |= 0x0003  # 128 samples per second

    # Write config register to ADS1115
    bus.write_i2c_block_data(ADC_ADDRESS, ADS1115_CONFIG_REG, [(config >> 8) & 0xFF, config & 0xFF])

# Function to read ADC value
def read_adc():
    # Wait for the conversion to complete
    time.sleep(0.1)
    
    # Read the conversion results
    result = bus.read_i2c_block_data(ADC_ADDRESS, ADS1115_CONVERSION_REG, 2)
    raw_adc = (result[0] << 8) | result[1]

    # Convert from two's complement
    if raw_adc > 0x7FFF:
        raw_adc -= 0x10000

    return raw_adc

# Function to convert ADC reading to percentage (adjust according to your sensor)
def adc_to_percentage(adc_value):
    max_value = 32767  # Maximum ADC value (16-bit resolution)
    min_value = -32768 # Minimum ADC value
    percentage = (adc_value - min_value) * 100 / (max_value - min_value)
    return percentage

# Function to convert ADC reading to voltage
def adc_to_voltage(adc_value):
    # ADS1115 is a 16-bit ADC, with Vref = 4.096V
    voltage = (adc_value * 4.096) / 32768.0
    return voltage

def open_valve():
    GPIO.output(relay_pin, GPIO.HIGH)  # Set pin high to activate relay

def close_valve():
    GPIO.output(relay_pin, GPIO.LOW)  # Set pin low to deactivate relay

# Function to control the relay/valve based on moisture level
def control_valve(moisture_percentage, weather_data):
    # Check if rain is indicated in weather data
    if "rain" in weather_data.get("description", "").lower():
        close_valve()  # Keep the valve closed
        return "closed (rain detected)"
    
    # If no rain, proceed with moisture-based control
    if moisture_percentage < 70:
        open_valve()
        return "opened (moisture < 70%)"
    else:
        close_valve()
        return "closed (moisture >= 70%)"

# Function to read sensor data
def read_sensors():
    # Read moisture sensor from ADC channel 0
    configure_ads1115(0)
    moisture_adc_value = read_adc()
    moisture_percentage = adc_to_percentage(moisture_adc_value)
    print("Moisture Percentage:", moisture_percentage)
    
    # Read light sensor from ADC channel 1
    configure_ads1115(1)
    light_adc_value = read_adc()
    light_voltage = adc_to_voltage(light_adc_value)
    print("Light Voltage:", light_voltage)

    return moisture_percentage

def get_weather(api_key, city):
    base_url = "http://api.openweathermap.org/data/2.5/weather"
    encoded_city = urllib.parse.quote(city)
    complete_url = f"{base_url}?q={encoded_city}&appid={api_key}&units=metric"
    with urllib.request.urlopen(complete_url) as response:
        data = json.loads(response.read().decode())
        if data["cod"] != "404":
            temperature_celsius = data["main"]["temp"]
            temperature_fahrenheit = celsius_to_fahrenheit(temperature_celsius)
            weather_info = {
                "city": data["name"],
                "temperature_celsius": temperature_celsius,
                "temperature_fahrenheit": temperature_fahrenheit,
                "description": data["weather"][0]["description"]
            }
             
            # Check if temperature is freezing (0 degrees Celsius or below)
            if temperature_celsius <= 0:
                weather_info["temperature_status"] = "Freezing"
            else:
                weather_info["temperature_status"] = "Normal"

            return weather_info
        else:
            return "City not found."

def celsius_to_fahrenheit(celsius):
    return (celsius * 9/5) + 32

def publish_to_aws(client, topic, message):
    client.connect()
    client.publish(topic, message, 1)
    client.disconnect()

if __name__ == "__main__":
    main()

