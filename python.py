import kagglehub

# Download latest version
path = kagglehub.dataset_download("mexwell/countries-states-and-cities-around-the-world")

print("Path to dataset files:", path)