# Where CI (and this session, once) pushes the Quarkus serving image.
resource "aws_ecr_repository" "serving" {
  name                 = "parvum-serving"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

# Untagged images pile up from every rebuild during iteration; expiring them
# after a week keeps storage cost negligible without touching anything
# App Runner currently references (which is always tagged).
resource "aws_ecr_lifecycle_policy" "serving" {
  repository = aws_ecr_repository.serving.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "expire untagged images after 7 days"
      selection = {
        tagStatus   = "untagged"
        countType   = "sinceImagePushed"
        countUnit   = "days"
        countNumber = 7
      }
      action = { type = "expire" }
    }]
  })
}

output "ecr_repository_url" {
  value = aws_ecr_repository.serving.repository_url
}
