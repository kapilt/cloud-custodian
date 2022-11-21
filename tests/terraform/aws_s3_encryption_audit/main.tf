resource "aws_s3_bucket" "example_a" {
  bucket = "c7n-aws-s3-encryption-audit-test-a"
  acl    = "private"
  server_side_encryption_configuration {
    rule {
      apply_server_side_encryption_by_default {
        sse_algorithm = "aws:kms"
      }
    }
  }
}

resource "aws_s3_bucket" "example_b" {
  bucket = "c7n-aws-s3-encryption-audit-test-b"
  acl    = "private"
  server_side_encryption_configuration {
    rule {
      apply_server_side_encryption_by_default {
        sse_algorithm = "AES256"
      }
    }
  }
}

resource "aws_s3_bucket" "example_c" {
  bucket = "c7n-aws-s3-encryption-audit-test-c"
  acl    = "private"
}

resource "aws_s3_bucket" "example_d" {
  bucket = "c7n-aws-s3-encryption-audit-test-d"
  acl    = "private"
}

resource "aws_s3_bucket_server_side_encryption_configuration" "example_d_sse" {
  bucket = aws_s3_bucket.example_d.bucket

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "AES256"
    }
  }
}
