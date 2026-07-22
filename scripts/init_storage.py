from app.config import settings


def main() -> None:
    for path in [
        settings.data_dir,
        settings.upload_dir,
        settings.parsed_dir,
        settings.metadata_dir,
    ]:
        path.mkdir(parents=True, exist_ok=True)
        print(path)


if __name__ == "__main__":
    main()
