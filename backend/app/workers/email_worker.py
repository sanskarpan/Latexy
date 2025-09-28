"""
Email notification worker for Phase 8.
"""

import asyncio
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, Optional, List

from celery import current_task
from ..core.celery_app import celery_app
from ..core.config import settings
from ..core.logging import get_logger
from ..core.redis import job_status_manager

logger = get_logger(__name__)


@celery_app.task(bind=True, name="app.workers.email_worker.send_notification_email_task")
def send_notification_email_task(
    self,
    recipient_email: str,
    subject: str,
    message: str,
    user_id: Optional[str] = None,
    email_type: str = "notification",
    template_data: Optional[Dict] = None,
    metadata: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Send notification email asynchronously.
    
    Args:
        recipient_email: Recipient email address
        subject: Email subject
        message: Email message body
        user_id: User ID for tracking
        email_type: Type of email (notification, completion, error, etc.)
        template_data: Data for email template
        metadata: Additional metadata
    
    Returns:
        Dict containing email sending result
    """
    task_id = self.request.id
    job_id = f"email_{task_id}"
    
    logger.info(f"Starting email notification task {task_id} for job {job_id}")
    
    try:
        # Set initial status
        asyncio.run(job_status_manager.set_job_status(
            job_id, 
            "processing", 
            {
                "task_id": task_id,
                "user_id": user_id,
                "recipient_email": recipient_email,
                "email_type": email_type,
                "started_at": time.time(),
                "metadata": metadata or {}
            }
        ))
        
        # Update progress
        asyncio.run(job_status_manager.set_job_progress(
            job_id, 
            20, 
            "Preparing email"
        ))
        
        # For now, we'll simulate email sending since we don't have SMTP configured
        # In production, you would configure SMTP settings and actually send emails
        
        # Simulate email preparation time
        time.sleep(1)
        
        # Update progress
        asyncio.run(job_status_manager.set_job_progress(
            job_id, 
            60, 
            "Sending email"
        ))
        
        # Simulate email sending
        start_time = time.time()
        
        # TODO: Implement actual email sending with SMTP
        # For now, just log the email details
        logger.info(f"Simulated email sent to {recipient_email}")
        logger.info(f"Subject: {subject}")
        logger.info(f"Message: {message[:100]}...")
        
        send_time = time.time() - start_time
        
        # Update progress
        asyncio.run(job_status_manager.set_job_progress(
            job_id, 
            90, 
            "Email sent successfully"
        ))
        
        # Prepare result data
        result_data = {
            "success": True,
            "task_id": task_id,
            "job_id": job_id,
            "message": "Email sent successfully",
            "recipient_email": recipient_email,
            "subject": subject,
            "email_type": email_type,
            "send_time": send_time,
            "user_id": user_id,
            "completed_at": time.time()
        }
        
        # Set final status and result
        asyncio.run(job_status_manager.set_job_status(
            job_id, 
            "completed", 
            {
                "task_id": task_id,
                "completed_at": time.time(),
                "send_time": send_time,
                "success": True
            }
        ))
        
        asyncio.run(job_status_manager.set_job_result(job_id, result_data))
        
        # Final progress update
        asyncio.run(job_status_manager.set_job_progress(
            job_id, 
            100, 
            "Email task completed"
        ))
        
        logger.info(f"Email notification task {task_id} completed for job {job_id}")
        return result_data
        
    except Exception as e:
        logger.error(f"Email notification task {task_id} failed for job {job_id}: {e}")
        
        error_data = {
            "success": False,
            "task_id": task_id,
            "job_id": job_id,
            "message": f"Email sending error: {str(e)}",
            "error": str(e),
            "recipient_email": recipient_email,
            "subject": subject,
            "email_type": email_type,
            "send_time": 0,
            "completed_at": time.time()
        }
        
        # Set error status
        asyncio.run(job_status_manager.set_job_status(
            job_id, 
            "failed", 
            {
                "task_id": task_id,
                "error": str(e),
                "completed_at": time.time()
            }
        ))
        
        asyncio.run(job_status_manager.set_job_result(job_id, error_data))
        
        # Retry logic for transient errors
        if self.request.retries < self.max_retries:
            logger.info(f"Retrying email notification task {task_id} (attempt {self.request.retries + 1})")
            raise self.retry(countdown=30, exc=e)
        
        return error_data


@celery_app.task(bind=True, name="app.workers.email_worker.send_completion_email_task")
def send_completion_email_task(
    self,
    recipient_email: str,
    user_name: str,
    job_type: str,
    job_id: str,
    success: bool,
    download_url: Optional[str] = None,
    user_id: Optional[str] = None,
    metadata: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Send job completion email asynchronously.
    
    Args:
        recipient_email: Recipient email address
        user_name: User's name
        job_type: Type of job (compilation, optimization, etc.)
        job_id: Job ID
        success: Whether the job was successful
        download_url: URL to download result (if applicable)
        user_id: User ID for tracking
        metadata: Additional metadata
    
    Returns:
        Dict containing email sending result
    """
    task_id = self.request.id
    email_job_id = f"completion_email_{task_id}"
    
    logger.info(f"Starting completion email task {task_id} for job {email_job_id}")
    
    try:
        # Prepare email content based on job result
        if success:
            subject = f"Your {job_type} is ready!"
            if job_type == "compilation":
                message = f"""
                Hi {user_name},

                Great news! Your LaTeX resume compilation has been completed successfully.

                Job ID: {job_id}
                Status: Completed
                {f'Download your PDF: {download_url}' if download_url else ''}

                Thank you for using Latexy!

                Best regards,
                The Latexy Team
                """
            elif job_type == "optimization":
                message = f"""
                Hi {user_name},

                Your resume optimization has been completed successfully!

                Job ID: {job_id}
                Status: Completed
                {f'Download your optimized resume: {download_url}' if download_url else ''}

                Your resume has been optimized for better ATS compatibility.

                Best regards,
                The Latexy Team
                """
            else:
                message = f"""
                Hi {user_name},

                Your {job_type} job has been completed successfully.

                Job ID: {job_id}
                Status: Completed

                Thank you for using Latexy!

                Best regards,
                The Latexy Team
                """
        else:
            subject = f"Your {job_type} encountered an issue"
            message = f"""
            Hi {user_name},

            We encountered an issue while processing your {job_type} request.

            Job ID: {job_id}
            Status: Failed

            Please try again or contact our support team if the issue persists.

            Best regards,
            The Latexy Team
            """
        
        # Send the notification email
        result = send_notification_email_task.apply(
            args=[recipient_email, subject, message],
            kwargs={
                "user_id": user_id,
                "email_type": "completion",
                "template_data": {
                    "user_name": user_name,
                    "job_type": job_type,
                    "job_id": job_id,
                    "success": success,
                    "download_url": download_url
                },
                "metadata": metadata
            }
        ).get()
        
        logger.info(f"Completion email task {task_id} completed for job {email_job_id}")
        return result
        
    except Exception as e:
        logger.error(f"Completion email task {task_id} failed for job {email_job_id}: {e}")
        
        error_data = {
            "success": False,
            "task_id": task_id,
            "job_id": email_job_id,
            "message": f"Completion email error: {str(e)}",
            "error": str(e),
            "recipient_email": recipient_email,
            "job_type": job_type,
            "original_job_id": job_id,
            "completed_at": time.time()
        }
        
        # Don't retry completion emails as they are not critical
        return error_data


@celery_app.task(bind=True, name="app.workers.email_worker.send_bulk_notification_task")
def send_bulk_notification_task(
    self,
    recipients: List[str],
    subject: str,
    message: str,
    email_type: str = "bulk_notification",
    template_data: Optional[Dict] = None,
    metadata: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Send bulk notification emails asynchronously.
    
    Args:
        recipients: List of recipient email addresses
        subject: Email subject
        message: Email message body
        email_type: Type of email
        template_data: Data for email template
        metadata: Additional metadata
    
    Returns:
        Dict containing bulk email sending result
    """
    task_id = self.request.id
    job_id = f"bulk_email_{task_id}"
    
    logger.info(f"Starting bulk email task {task_id} for job {job_id} with {len(recipients)} recipients")
    
    try:
        # Set initial status
        asyncio.run(job_status_manager.set_job_status(
            job_id, 
            "processing", 
            {
                "task_id": task_id,
                "recipient_count": len(recipients),
                "email_type": email_type,
                "started_at": time.time(),
                "metadata": metadata or {}
            }
        ))
        
        successful_sends = 0
        failed_sends = 0
        results = []
        
        for i, recipient in enumerate(recipients):
            try:
                # Update progress
                progress = int((i / len(recipients)) * 90) + 10
                asyncio.run(job_status_manager.set_job_progress(
                    job_id, 
                    progress, 
                    f"Sending email {i+1}/{len(recipients)}"
                ))
                
                # Send individual email
                result = send_notification_email_task.apply(
                    args=[recipient, subject, message],
                    kwargs={
                        "email_type": email_type,
                        "template_data": template_data,
                        "metadata": {"bulk_job_id": job_id, "recipient_index": i}
                    }
                ).get()
                
                if result.get("success", False):
                    successful_sends += 1
                else:
                    failed_sends += 1
                
                results.append({
                    "recipient": recipient,
                    "success": result.get("success", False),
                    "error": result.get("error") if not result.get("success", False) else None
                })
                
            except Exception as e:
                logger.error(f"Failed to send email to {recipient}: {e}")
                failed_sends += 1
                results.append({
                    "recipient": recipient,
                    "success": False,
                    "error": str(e)
                })
        
        # Prepare result data
        result_data = {
            "success": successful_sends > 0,
            "task_id": task_id,
            "job_id": job_id,
            "message": f"Bulk email completed: {successful_sends} successful, {failed_sends} failed",
            "total_recipients": len(recipients),
            "successful_sends": successful_sends,
            "failed_sends": failed_sends,
            "results": results,
            "email_type": email_type,
            "completed_at": time.time()
        }
        
        # Set final status and result
        final_status = "completed" if successful_sends > 0 else "failed"
        asyncio.run(job_status_manager.set_job_status(
            job_id, 
            final_status, 
            {
                "task_id": task_id,
                "completed_at": time.time(),
                "successful_sends": successful_sends,
                "failed_sends": failed_sends,
                "success": successful_sends > 0
            }
        ))
        
        asyncio.run(job_status_manager.set_job_result(job_id, result_data))
        
        # Final progress update
        asyncio.run(job_status_manager.set_job_progress(
            job_id, 
            100, 
            "Bulk email task completed"
        ))
        
        logger.info(f"Bulk email task {task_id} completed for job {job_id}: {successful_sends}/{len(recipients)} successful")
        return result_data
        
    except Exception as e:
        logger.error(f"Bulk email task {task_id} failed for job {job_id}: {e}")
        
        error_data = {
            "success": False,
            "task_id": task_id,
            "job_id": job_id,
            "message": f"Bulk email error: {str(e)}",
            "error": str(e),
            "total_recipients": len(recipients),
            "successful_sends": 0,
            "failed_sends": len(recipients),
            "completed_at": time.time()
        }
        
        # Set error status
        asyncio.run(job_status_manager.set_job_status(
            job_id, 
            "failed", 
            {
                "task_id": task_id,
                "error": str(e),
                "completed_at": time.time()
            }
        ))
        
        asyncio.run(job_status_manager.set_job_result(job_id, error_data))
        
        return error_data


# Utility functions to submit email jobs
def submit_notification_email(
    recipient_email: str,
    subject: str,
    message: str,
    user_id: Optional[str] = None,
    email_type: str = "notification",
    template_data: Optional[Dict] = None,
    metadata: Optional[Dict] = None
) -> str:
    """
    Submit notification email job to queue.
    
    Returns:
        job_id: Job ID for tracking
    """
    # Submit task to queue
    task = send_notification_email_task.apply_async(
        args=[recipient_email, subject, message],
        kwargs={
            "user_id": user_id,
            "email_type": email_type,
            "template_data": template_data,
            "metadata": metadata
        },
        queue="email"
    )
    
    job_id = f"email_{task.id}"
    logger.info(f"Submitted notification email job {job_id} with task {task.id}")
    return job_id


def submit_completion_email(
    recipient_email: str,
    user_name: str,
    job_type: str,
    job_id: str,
    success: bool,
    download_url: Optional[str] = None,
    user_id: Optional[str] = None,
    metadata: Optional[Dict] = None
) -> str:
    """
    Submit completion email job to queue.
    
    Returns:
        job_id: Job ID for tracking
    """
    # Submit task to queue
    task = send_completion_email_task.apply_async(
        args=[recipient_email, user_name, job_type, job_id, success],
        kwargs={
            "download_url": download_url,
            "user_id": user_id,
            "metadata": metadata
        },
        queue="email"
    )
    
    email_job_id = f"completion_email_{task.id}"
    logger.info(f"Submitted completion email job {email_job_id} with task {task.id}")
    return email_job_id
