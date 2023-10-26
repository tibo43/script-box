from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials
import json
import os.path
import argparse
import logging

def parse_args(arg_input=None):
    parser = argparse.ArgumentParser(description='Upload photos to Google Photos.')
    parser.add_argument('--auth ', metavar='auth_file', dest='auth_file',
                    help='file for reading/storing user authentication tokens')
    parser.add_argument('--folder_path', metavar='photos_folder_path', dest='photos_folder_path',
                    help='The path of folder containing all photos.')
    parser.add_argument('--log', metavar='log_file', dest='log_file',
                    help='name of output file for log messages')
    return parser.parse_args(arg_input)

def auth(auth_token_file,scopes):
    flow = InstalledAppFlow.from_client_secrets_file(
        auth_token_file,
        scopes=scopes)
    credentials = flow.run_local_server(host='localhost',
                                        port=8080,
                                        authorization_prompt_message="",
                                        success_message='The auth flow is complete; you may close this window.',
                                        open_browser=True)
    return credentials

def get_authorized_session(auth_token_file):
    scopes=['https://www.googleapis.com/auth/photoslibrary',
            'https://www.googleapis.com/auth/photoslibrary.sharing']
    cred = None
    if auth_token_file:
        try:
            cred = Credentials.from_authorized_user_file(auth_token_file, scopes)
        except OSError as err:
            logging.debug("Error opening auth token file - {0}".format(err))
        except ValueError:
            logging.debug("Error loading auth tokens - Incorrect format")
    if not cred:
        cred = auth(auth_token_file,scopes)
    session = AuthorizedSession(cred)
    if auth_token_file:
        try:
            save_cred(cred, auth_token_file)
        except OSError as err:
            logging.debug("Could not save auth tokens - {0}".format(err))

    return session


def save_cred(cred, auth_file):

    cred_dict = {
        'token': cred.token,
        'refresh_token': cred.refresh_token,
        'id_token': cred.id_token,
        'scopes': cred.scopes,
        'token_uri': cred.token_uri,
        'client_id': cred.client_id,
        'client_secret': cred.client_secret
    }

    with open(auth_file, 'w') as f:
        print(json.dumps(cred_dict), file=f)

def getAlbums(session, appCreatedOnly=False):
    params = {
            'excludeNonAppCreatedData': appCreatedOnly
    }
    while True:
        albums = session.get('https://photoslibrary.googleapis.com/v1/albums', params=params).json()
        logging.debug("Server response: {}".format(albums))
        if 'albums' in albums:
            for a in albums["albums"]:
                yield a
            if 'nextPageToken' in albums:
                params["pageToken"] = albums["nextPageToken"]
            else:
                return
        else:
            return

def create_or_retrieve_album(session, album_title):
    # Find albums created by this app to see if one matches album_title
    for a in getAlbums(session, True):
        if a["title"].lower() == album_title.lower():
            album_id = a["id"]
            logging.info("Uploading into EXISTING photo album -- \'{0}\'".format(album_title))
            return album_id
    # No matches, create new album
    create_album_body = json.dumps({"album":{"title": album_title}})
    resp = session.post('https://photoslibrary.googleapis.com/v1/albums', create_album_body).json()
    logging.debug("Server response: {}".format(resp))
    if "id" in resp:
        logging.info("Uploading into NEW photo album -- \'{0}\'".format(album_title))
        return resp['id']
    else:
        logging.error("Could not find or create photo album '\{0}\'. Server Response: {1}".format(album_title, resp))
        return None

def upload_photos_to_google_photos(session, photos_folder_path):
    # List the folders
    folders = os.listdir(photos_folder_path)
    # Iterate over each folder and upload the photos
    for folder in folders:
        if os.path.isdir(os.path.join(photos_folder_path, folder)):
            album_id = create_or_retrieve_album(session, folder)
            session.headers["Content-type"] = "application/octet-stream"
            session.headers["X-Goog-Upload-Protocol"] = "raw"
            photos = os.listdir(os.path.join(photos_folder_path, folder))
            for photo in photos:
                try:
                    photo_file = open(os.path.join(photos_folder_path, folder,photo), mode='rb')
                    photo_bytes = photo_file.read()
                except OSError as err:
                    logging.error("Could not read file \'{0}\' -- {1}".format(photo, err))
                    continue
                session.headers["X-Goog-Upload-File-Name"] = os.path.basename(photo)
                logging.info("Uploading photo -- \'{}\'".format(photo))
                upload_token = session.post('https://photoslibrary.googleapis.com/v1/uploads', photo_bytes)
                if (upload_token.status_code == 200) and (upload_token.content):
                    create_body = json.dumps({"albumId":album_id, "newMediaItems":[{"description":"","simpleMediaItem":{"uploadToken":upload_token.content.decode()}}]}, indent=4)
                    resp = session.post('https://photoslibrary.googleapis.com/v1/mediaItems:batchCreate', create_body).json()
                    logging.debug("Server response: {}".format(resp))
                    if "newMediaItemResults" in resp:
                        status = resp["newMediaItemResults"][0]["status"]
                        if status.get("code") and (status.get("code") > 0):
                            logging.error("Could not add \'{0}\' to library -- {1}".format(os.path.basename(photo), status["message"]))
                        else:
                            logging.info("Added \'{}\' to library and album \'{}\' ".format(os.path.basename(photo), folder))
                    else:
                        logging.error("Could not add \'{0}\' to library. Server Response -- {1}".format(os.path.basename(photo), resp))
                else:
                    logging.error("Could not upload \'{0}\'. Server Response - {1}".format(os.path.basename(photo), upload_token))
    try:
        del(session.headers["Content-type"])
        del(session.headers["X-Goog-Upload-Protocol"])
        del(session.headers["X-Goog-Upload-File-Name"])
    except KeyError:
        pass
if __name__ == "__main__":
    args = parse_args()

    logging.basicConfig(format='%(asctime)s %(module)s.%(funcName)s:%(levelname)s:%(message)s',
                    datefmt='%m/%d/%Y %I_%M_%S %p',
                    filename=args.log_file,
                    level=logging.INFO)
    session = get_authorized_session(args.auth_file)
    upload_photos_to_google_photos(session, args.photos_folder_path)