FROM python:3.12

# set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Install system dependencies for fonts and other packages
RUN apt-get update && apt-get install -y \
    fonts-noto \
    fonts-noto-cjk \
    fonts-noto-cjk-extra \
    fontconfig \
    wget \
    unzip \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# install python dependencies
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Install assets (fonts and flags)
RUN mkdir -p static/flags static/logos
RUN python3 install_assets.py

# Update font cache
RUN fc-cache -fv

# Set UP
RUN python manage.py collectstatic --no-input
RUN python manage.py makemigrations
RUN python manage.py migrate

RUN python manage.py generate_people
RUN python manage.py initialisedb
RUN python manage.py createsuperuser_with_password --username ${DJANGO_SUPERUSER_USERNAME} --password ${DJANGO_SUPERUSER_PASSWORD}


#__API_GENERATOR__
RUN python manage.py generate-api -f
#__API_GENERATOR__END

# Start Server
EXPOSE 5005
CMD ["gunicorn", "--config", "gunicorn-cfg.py", "core.asgi"]
