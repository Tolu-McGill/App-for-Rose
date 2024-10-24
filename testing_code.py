from google.cloud import vision
import io
import os


# Use raw string to set the correct path to your credentials
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = r"C:\Users\dudeo\Downloads\Python Project for Rose\bright-drake-439601-i4-bd1026251962.json"
# Initialize the Vision API client
client = vision.ImageAnnotatorClient()

# Path to the image you want to analyze
image_path = r"C:\Users\dudeo\Downloads\receipt_sample.jpeg"

# Load the image into memory
with io.open(image_path, 'rb') as image_file:
    content = image_file.read()

# Create an image object
image = vision.Image(content=content)

# Send the image to Google Cloud Vision API for text detection
response = client.text_detection(image=image)
texts = response.text_annotations

# Print the detected text
print('Texts:')
for text in texts:
    print(f"{text.description}")
