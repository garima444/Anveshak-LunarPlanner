FROM continuumio/miniconda3:latest

WORKDIR /app

# Install GDAL stack via conda-forge (handles native libs: libgdal, libcurl, openjpeg)
# libcurl is required for /vsicurl/ HTTP COG streaming
RUN conda install -c conda-forge \
    gdal \
    rasterio \
    pyproj \
    openjpeg \
    libcurl \
    numpy \
    scipy \
    scikit-learn \
    --yes --quiet

# Install Python packages via pip
COPY requirements.txt .
RUN pip install -r requirements.txt --no-cache-dir

# Copy application source
COPY . .

# Create runtime directories (also created by Config, but good for Docker layer caching)
RUN mkdir -p uploads temp data/bundled

# Expose API port
EXPOSE 8000

# Start server — single worker to avoid duplicating terrain cache RAM usage
CMD uvicorn main:app \
    --host 0.0.0.0 \
    --port ${PORT:-8000} \
    --workers 1
