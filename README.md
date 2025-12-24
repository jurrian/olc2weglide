# olc2weglide

### [🚀 Live Website: olc2weglide.nl](https://olc2weglide.nl)

Open source project to easily migrate all your [OLC](https://www.onlinecontest.org/) flights to [WeGlide.org](https://weglide.org/).  

Vue.js frontend + python Tornado backend.  

I admit this not the cleanest code that I ever wrote, but it does the job :)

## Project Status
This project is **stable** and can be used as-is. 
- **Maintenance:** No new features will be developed by the maintainer.
- **Bugs:** Feel free to open an issue for bugs.
- **Contributions:** If you want to add a feature:
  1. Open an issue to discuss the feature.
  2. Write the code and open a PR.
  3. Merged features will be deployed to the main website!

Users are encouraged to freely use the project and make adjustments for their own use.

## Getting Started

### Prerequisites
- Node.js (v20 or higher)
- Python (v3.12 or higher)
- Docker
- pnpm

### Frontend Development
To run the frontend locally:
```bash
npm install -g pnpm@latest-10
pnpm install
# Important to run this in the root directory where .env lives
pnpm run dev
```

### Backend & Infrastructure
The project uses Docker to manage the API and Redis. It's also possible to run outside of Docker, 
but .env vars will not be loaded automatically and need to be set manually.
```bash
cp .env-default .env
# Don't forget to fill in the environment variables in the .env file
docker compose up -d --build api redis
```

> [!WARNING]
> **IP Restrictions:** Running this project locally might be restricted by WeGlide. WeGlide currently blocks non-whitelisted IP addresses from using certain API endpoints. If you experience issues connecting to WeGlide locally, you may need to request whitelisting from WeGlide or run the app from a whitelisted server.

## Deployment
Deployment is handled via the `deploy.sh` script:
```bash
./deploy.sh
```
*Note: Ensure you have copied the necessary `.env-default` file to `.env` and filled in the environment variables.*

## License
This project is open source and licensed for free use under the MIT License - see the [LICENSE](LICENSE) file for details.
