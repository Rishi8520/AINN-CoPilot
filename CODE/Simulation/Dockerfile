# =====================================================================
# STEP 1: Foundation Layer
# =====================================================================
FROM ubuntu:22.04

USER root
ENV DEBIAN_FRONTEND=noninteractive

# =====================================================================
# STEP 2: System Dependencies & Python Libraries
# =====================================================================
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl git ca-certificates build-essential clang bison flex perl \
    python3 python3-pip python3-numpy python3-scipy python3-pandas \
    python3-matplotlib python3-posix-ipc \
    libxml2-dev zlib1g-dev default-jre shared-mime-info xdg-user-dirs \
    qtbase5-dev qtchooser qt5-qmake qtbase5-dev-tools libqt5opengl5-dev \
    libosmesa6-dev libgl1-mesa-glx libgl1-mesa-dri libxft2 libxss1 \
    && rm -rf /var/lib/apt/lists/*

# =====================================================================
# STEP 3: Automated Source Installation
# =====================================================================
WORKDIR /opt

# 1. OMNeT++ 6.0
RUN wget https://github.com/omnetpp/omnetpp/releases/download/omnetpp-6.0/omnetpp-6.0-linux-x86_64.tgz --no-check-certificate \
    && tar -xzf omnetpp-6.0-linux-x86_64.tgz && rm omnetpp-6.0-linux-x86_64.tgz

# 2. INET 4.5
RUN wget https://github.com/inet-framework/inet/releases/download/v4.5.0/inet-4.5.0-src.tgz --no-check-certificate \
    && tar -xzf inet-4.5.0-src.tgz && rm inet-4.5.0-src.tgz && mv inet4.5 inet

# 3. Simu5G
#COPY ./simu5g /opt/simu5g
COPY Simulation/simu5g /opt/simu5g

# =====================================================================
# STEP 4: Path & Environment Configuration
# =====================================================================
ENV OMNETPP_HOME=/opt/omnetpp-6.0
ENV PATH="/opt/omnetpp-6.0/bin:${PATH}"

# Configure build
RUN cd /opt/omnetpp-6.0 \
    && cp configure.user.dist configure.user \
    && . ./setenv \
    && ./configure WITH_QTENV=yes WITH_OSG=no WITH_OSGEARTH=no

# =====================================================================
# STEP 5: Workspace Setup
# =====================================================================
WORKDIR /workspace
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt
#COPY ./app ./app
COPY Simulation/app ./app

EXPOSE 7000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7000"]
