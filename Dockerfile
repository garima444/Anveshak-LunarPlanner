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
    wget \
    --yes --quiet

# Install Python packages via pip
COPY requirements.txt .
RUN pip install -r requirements.txt --no-cache-dir

# Copy application source
COPY . .

# Create runtime directories (also created by Config, but good for Docker layer caching)
RUN mkdir -p uploads temp data/bundled

# ---------------------------------------------------------------------------
# Bundle data files — downloaded from GitHub Releases at build time so the
# app never depends on NASA COG streaming in production.
# Files are baked into this image layer; no network call at runtime.
# To update data: bump the release tag and rebuild.
# ---------------------------------------------------------------------------
ARG DATA_RELEASE=https://github.com/garima444/Anveshak-LunarPlanner/releases/download/v1.0-data

RUN mkdir -p data/dem/DEM_20M data/PSR data/SolarIllumination \
             data/EarthVisibility data/SkyVisibility data/roughness

RUN wget -q "$DATA_RELEASE/LDEM_80S_20M.JP2" \
         -O data/dem/DEM_20M/LDEM_80S_20M.JP2 && \
    wget -q "$DATA_RELEASE/LDEC_80S_20M.JP2" \
         -O data/dem/DEM_20M/LDEC_80S_20M.JP2 && \
    wget -q "$DATA_RELEASE/AVGVISIB_85S_060M_201608.tiff" \
         -O data/SolarIllumination/AVGVISIB_85S_060M_201608.tiff && \
    wget -q "$DATA_RELEASE/LPSR_85S_060M_201608.tiff" \
         -O data/PSR/LPSR_85S_060M_201608.tiff && \
    wget -q "$DATA_RELEASE/AVGVISIB_85S_060M_201608_EARTH.tiff" \
         -O data/EarthVisibility/AVGVISIB_85S_060M_201608_EARTH.tiff && \
    wget -q "$DATA_RELEASE/SKYV_65S_240M.tiff" \
         -O data/SkyVisibility/SKYV_65S_240M.tiff && \
    wget -q "$DATA_RELEASE/MAS_57M_16.JP2" \
         -O data/roughness/MAS_57M_16.JP2 && \
    wget -q "$DATA_RELEASE/MAS_225M_16.JP2" \
         -O data/roughness/MAS_225M_16.JP2 && \
    wget -q "$DATA_RELEASE/MAS_560M_16.JP2" \
         -O data/roughness/MAS_560M_16.JP2 && \
    wget -q "$DATA_RELEASE/HE_8.JP2" \
         -O data/roughness/HE_8.JP2

# Expose API port
EXPOSE 8000

# Start server — single worker to avoid duplicating terrain cache RAM usage
CMD uvicorn main:app \
    --host 0.0.0.0 \
    --port ${PORT:-8000} \
    --workers 1
