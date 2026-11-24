# Three targets from one file:
#   test     - runs the unit tests (docker build --target test, then docker run)
#   runtime  - the service image (the default)
# Building and testing happen inside the SDK image, so nothing but Docker is
# assumed on the machine - the same contract the Java service's wrapper gives.
FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build
WORKDIR /src
# Restore from the project files alone, so this layer is reused until a
# dependency changes rather than on every source edit.
COPY Parvum.Internal.Api/Parvum.Internal.Api.csproj Parvum.Internal.Api/
COPY Parvum.Internal.Api.Tests/Parvum.Internal.Api.Tests.csproj Parvum.Internal.Api.Tests/
RUN dotnet restore Parvum.Internal.Api.Tests/Parvum.Internal.Api.Tests.csproj
COPY . .

FROM build AS test
CMD ["dotnet", "test", "Parvum.Internal.Api.Tests", "--nologo"]

FROM build AS publish
RUN dotnet publish Parvum.Internal.Api -c Release -o /app

FROM mcr.microsoft.com/dotnet/aspnet:10.0 AS runtime
WORKDIR /app
COPY --from=publish /app .
ENV ASPNETCORE_HTTP_PORTS=8080
EXPOSE 8080
# The image's unprivileged user: the service needs no write access to its own files.
USER app
ENTRYPOINT ["dotnet", "Parvum.Internal.Api.dll"]
